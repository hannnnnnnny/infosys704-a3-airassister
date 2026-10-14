"""Sign-in, role separation and signed-token behavior for the demo accounts."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from refund_support import (APIServer, PASSENGER, PASSENGER_PASSWORD, STAFF, STAFF_PASSWORD,
                            FakeSAP, make_auth, public_dir, server)


def environment_without_secrets():
    return {name: value for name, value in os.environ.items() if not name.startswith("AIRASSIST_")}


class AuthUnitTests(unittest.TestCase):
    def test_only_salted_hashes_are_kept_in_memory(self):
        auth = make_auth()
        for meta in auth.accounts.values():
            self.assertIsInstance(meta["salt"], bytes)
            self.assertIsInstance(meta["hash"], bytes)
        self.assertNotIn(PASSENGER_PASSWORD, repr(auth.accounts))
        self.assertNotIn(STAFF_PASSWORD, repr(auth.accounts))
        self.assertNotEqual(auth.accounts[PASSENGER]["salt"], auth.accounts[STAFF]["salt"])

    def test_matching_password_returns_account_and_clears_failures(self):
        auth = make_auth()
        with self.assertRaises(server.APIError):
            auth.authenticate(STAFF, "wrong", "127.0.0.1")
        account = auth.authenticate(STAFF, STAFF_PASSWORD, "127.0.0.1")
        self.assertEqual(account["role"], "staff")
        self.assertEqual(account["displayName"], "Refunds team")

    def test_unknown_user_and_wrong_password_share_one_error(self):
        auth = make_auth()
        with self.assertRaises(server.APIError) as unknown:
            auth.authenticate("nobody", "whatever", "127.0.0.1")
        with self.assertRaises(server.APIError) as wrong:
            auth.authenticate(STAFF, "whatever", "127.0.0.1")
        self.assertEqual((unknown.exception.status, unknown.exception.code), (401, "INVALID_CREDENTIALS"))
        self.assertEqual(unknown.exception.message, wrong.exception.message)

    def test_token_round_trip_carries_role_and_subject(self):
        auth = make_auth()
        token = auth.issue_token(auth.accounts[PASSENGER], PASSENGER)
        claims = auth.verify_token(token)
        self.assertEqual((claims["role"], claims["subject"]), ("passenger", PASSENGER))

    def test_expired_and_tampered_tokens_are_rejected(self):
        auth = make_auth()
        token = auth.issue_token(auth.accounts[STAFF], STAFF, now=1_000.0)
        with self.assertRaises(server.APIError) as expired:
            auth.verify_token(token, now=1_000.0 + server.TOKEN_SECONDS)
        self.assertEqual((expired.exception.status, expired.exception.code), (401, "SESSION_EXPIRED"))
        body, signature = token.split(".")
        with self.assertRaises(server.APIError):
            auth.verify_token(body + "." + ("0" if signature[-1] != "0" else "1") + signature[1:])
        forged = "eyJleHAiOjk5OTk5OTk5OTksInJvbGUiOiJzdGFmZiIsInN1YmplY3QiOiJhZG1pbiJ9.0000"
        with self.assertRaises(server.APIError):
            auth.verify_token(forged)
        with self.assertRaises(server.APIError):
            auth.verify_token("not-a-token")

    def test_rate_limit_is_keyed_by_username_and_client_address(self):
        auth = make_auth()
        for _ in range(server.LOGIN_MAX_FAILURES):
            with self.assertRaises(server.APIError) as wrong:
                auth.authenticate(STAFF, "wrong", "10.0.0.1")
            self.assertEqual(wrong.exception.status, 401)
        with self.assertRaises(server.APIError) as limited:
            auth.authenticate(STAFF, STAFF_PASSWORD, "10.0.0.1")
        self.assertEqual(limited.exception.status, 429)
        # A different client address and a different username stay available.
        self.assertEqual(auth.authenticate(STAFF, STAFF_PASSWORD, "10.0.0.2")["role"], "staff")
        self.assertEqual(auth.authenticate(PASSENGER, PASSENGER_PASSWORD, "10.0.0.1")["role"], "passenger")

    def test_build_auth_generates_locally_and_prefers_configured_secrets(self):
        base = environment_without_secrets()
        with patch.dict("os.environ", base, clear=True):
            auth, generated = server.build_auth(deployed=False)
            self.assertEqual(set(generated), {"AIRASSIST_PASSENGER_PASSWORD", "AIRASSIST_STAFF_PASSWORD"})
            self.assertTrue(all(len(value) >= 12 for value in generated.values()))
            self.assertTrue(all(meta["available"] for meta in auth.accounts.values()))
        configured = {**base, "AIRASSIST_PASSENGER_PASSWORD": "p", "AIRASSIST_STAFF_PASSWORD": "s",
                      "AIRASSIST_SESSION_SECRET": "preferred-secret", "BLOB_READ_WRITE_TOKEN": "blob-token"}
        with patch.dict("os.environ", configured, clear=True):
            local, generated = server.build_auth(deployed=False)
            self.assertEqual(generated, {})
            self.assertEqual(local.session_secret, b"preferred-secret")
            deployed, generated_deployed = server.build_auth(deployed=True)
            self.assertEqual(generated_deployed, {})
            self.assertEqual(deployed.session_secret, b"preferred-secret")
        blob_only = {**base, "AIRASSIST_PASSENGER_PASSWORD": "p", "AIRASSIST_STAFF_PASSWORD": "s",
                     "BLOB_READ_WRITE_TOKEN": "blob-token"}
        with patch.dict("os.environ", blob_only, clear=True):
            deployed, _ = server.build_auth(deployed=True)
            self.assertEqual(deployed.session_secret, b"blob-token")

    def test_deployed_without_passwords_refuses_sign_in(self):
        auth = make_auth(deployed=True, passenger=None, staff=None)
        with self.assertRaises(server.APIError) as unavailable:
            auth.authenticate(PASSENGER, "anything", "127.0.0.1")
        self.assertEqual((unavailable.exception.status, unavailable.exception.code),
                         (503, "SIGNIN_UNAVAILABLE"))


class LoginHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="runtime-", dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        folder = Path(self.temp.name)
        self.auth = make_auth()
        self.api = APIServer(server.ApplicationStore(folder / "data.sqlite3"), FakeSAP(), public_dir(folder), self.auth)
        self.addCleanup(self.api.close)

    def test_sign_in_returns_token_role_and_display_name(self):
        passenger = self.api.login(PASSENGER, PASSENGER_PASSWORD)
        self.assertEqual((passenger["role"], passenger["displayName"]), ("passenger", "Mark Don"))
        self.assertTrue(passenger["token"])
        staff = self.api.login(STAFF, STAFF_PASSWORD)
        self.assertEqual((staff["role"], staff["displayName"]), ("staff", "Refunds team"))

    def test_wrong_password_and_unknown_user_share_one_response(self):
        _, _, first = self.api.json_call("/api/auth/login", {"username": STAFF, "password": "wrong"})
        _, _, second = self.api.json_call("/api/auth/login", {"username": "ghost", "password": "wrong"})
        self.assertEqual(first, second)
        self.assertEqual(first["error"]["code"], "INVALID_CREDENTIALS")

    def test_five_failures_lock_one_username_and_client_only(self):
        for _ in range(server.LOGIN_MAX_FAILURES):
            self.assertEqual(self.api.json_call("/api/auth/login",
                                                {"username": STAFF, "password": "wrong"})[0], 401)
        self.assertEqual(self.api.json_call("/api/auth/login",
                                            {"username": STAFF, "password": STAFF_PASSWORD})[0], 429)
        self.assertEqual(self.api.json_call("/api/auth/login",
                                            {"username": PASSENGER, "password": PASSENGER_PASSWORD})[0], 200)

    def test_malformed_sign_in_body_is_rejected(self):
        self.assertEqual(self.api.json_call("/api/auth/login", {"username": STAFF})[0], 400)
        self.assertEqual(self.api.json_call("/api/auth/login", {"username": "", "password": ""})[0], 400)
        self.assertEqual(self.api.raw("/api/auth/login", b"{not json")[0], 400)
        self.assertEqual(self.api.raw("/api/auth/login", json.dumps(
            {"username": STAFF, "password": STAFF_PASSWORD}).encode(), content_type="text/plain")[0], 415)


if __name__ == "__main__":
    unittest.main()
