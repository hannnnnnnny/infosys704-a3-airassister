"""Passenger endpoints: live SAP quote, one-step full refund submission and receipts."""
import json
import tempfile
import unittest
import uuid
from pathlib import Path

from refund_support import (PASSENGER, PASSENGER_PASSWORD, STAFF, STAFF_PASSWORD,
                            APIServer, FakeSAP, make_auth, public_dir, server)


def submission(email="mark.don@example.com", request_key=None, confirmed=True):
    return {"email": email, "confirmed": confirmed, "requestKey": request_key or str(uuid.uuid4())}


class PassengerAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="runtime-", dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.sap = FakeSAP()
        self.store = server.ApplicationStore(self.folder / "data.sqlite3")
        self.api = APIServer(self.store, self.sap, public_dir(self.folder), make_auth())
        self.addCleanup(self.api.close)
        self.token = self.api.login(PASSENGER, PASSENGER_PASSWORD)["token"]

    def auth(self, token=None):
        return {"Authorization": "Bearer " + (self.token if token is None else token)}

    def test_me_returns_live_sap_quote_and_no_request_initially(self):
        status, _, body = self.api.json_call("/api/me", headers=self.auth())
        self.assertEqual(status, 200)
        self.assertEqual(body["displayName"], "Mark Don")
        self.assertEqual(body["flight"]["flight"], "NZ6")
        self.assertEqual(body["flight"]["flightStatus"], "cancelled")
        self.assertEqual(body["booking"]["reference"], "NZ7K2H")
        self.assertEqual(body["booking"]["sapCreditMemoRequest"], "60000073")
        self.assertEqual(body["quote"], {"sapDocument": "60000073", "amount": 250.0, "currency": "NZD",
                                         "processStatus": "A", "fetchedAt": "2026-10-14T00:00:00Z"})
        self.assertIsNone(body["quoteError"])
        self.assertIsNone(body["request"])
        self.assertEqual(self.sap.calls, ["60000073"])

    def test_me_reports_a_clear_quote_error_instead_of_a_fallback(self):
        self.sap.error = server.APIError(503, "SAP_UNCONFIGURED", "Configure the personal SAP API key.")
        status, _, body = self.api.json_call("/api/me", headers=self.auth())
        self.assertEqual(status, 200)
        self.assertIsNone(body["quote"])
        self.assertEqual(body["quoteError"]["code"], "SAP_UNCONFIGURED")
        self.assertIsNone(body["request"])

    def test_sign_in_is_required_for_passenger_endpoints(self):
        for path in ("/api/me", "/api/refund-requests/receipt"):
            self.assertEqual(self.api.call(path)[0], 401, path)
        self.assertEqual(self.api.json_call("/api/refund-requests", submission())[0], 401)

    def test_submit_creates_a_pending_full_refund_request_with_the_quote_snapshot(self):
        status, _, body = self.api.json_call("/api/refund-requests", submission(), headers=self.auth())
        self.assertEqual(status, 201)
        self.assertTrue(body["created"])
        record = body["request"]
        self.assertTrue(record["reference"].startswith("AF-"))
        self.assertEqual((record["bookingReference"], record["passengerName"]), ("NZ7K2H", "Mark Don"))
        self.assertEqual((record["reason"], record["refundType"]), ("flight_disruption", "full"))
        self.assertEqual((record["amount"], record["currency"], record["sapDocument"]), (250.0, "NZD", "60000073"))
        self.assertEqual((record["sapStatus"], record["quoteSource"]), ("A", "live"))
        self.assertEqual((record["status"], record["version"], record["route"]), ("pending", 1, "fast_track"))
        self.assertEqual([event["type"] for event in record["events"]], ["submitted"])
        self.assertIsNotNone(self.store.request_for_booking("NZ7K2H"))

    def test_submission_is_blocked_without_a_live_quote(self):
        self.sap.error = server.APIError(503, "SAP_UNAVAILABLE", "SAP is temporarily unavailable.")
        status, _, body = self.api.json_call("/api/refund-requests", submission(), headers=self.auth())
        self.assertEqual(status, 503)
        self.assertEqual(body["error"]["code"], "SAP_UNAVAILABLE")
        self.assertIsNone(self.store.request_for_booking("NZ7K2H"))

    def test_submission_is_blocked_when_sap_has_no_amount(self):
        record = dict(self.sap.record)
        record["totalNetAmount"] = None
        self.sap.record = record
        status, _, body = self.api.json_call("/api/refund-requests", submission(), headers=self.auth())
        self.assertEqual(status, 502)
        self.assertEqual(body["error"]["code"], "SAP_QUOTE_INCOMPLETE")
        self.assertIsNone(self.store.request_for_booking("NZ7K2H"))

    def test_repeating_the_same_request_key_returns_the_same_request(self):
        body = submission()
        _, _, first = self.api.json_call("/api/refund-requests", body, headers=self.auth())
        self.sap.calls.clear()
        status, _, second = self.api.json_call("/api/refund-requests", body, headers=self.auth())
        self.assertEqual(status, 200)
        self.assertFalse(second["created"])
        self.assertEqual(second["request"], first["request"])
        # A repeat never reads SAP again and never creates a second record.
        self.assertEqual(self.sap.calls, [])
        self.assertEqual(len(self.store.staff_requests()), 2)

    def test_same_request_key_with_a_different_payload_is_a_conflict(self):
        body = submission()
        self.api.json_call("/api/refund-requests", body, headers=self.auth())
        changed = dict(body, email="someone.else@example.com")
        status, _, response = self.api.json_call("/api/refund-requests", changed, headers=self.auth())
        self.assertEqual(status, 409)
        self.assertEqual(response["error"]["code"], "IDEMPOTENCY_CONFLICT")

    def test_one_request_per_booking_returns_the_original(self):
        _, _, first = self.api.json_call("/api/refund-requests", submission(), headers=self.auth())
        status, _, second = self.api.json_call("/api/refund-requests", submission(), headers=self.auth())
        self.assertEqual(status, 200)
        self.assertFalse(second["created"])
        self.assertEqual(second["request"]["reference"], first["request"]["reference"])
        self.assertEqual(len(self.store.staff_requests()), 2)

    def test_confirmation_and_email_are_validated(self):
        self.assertEqual(self.api.json_call("/api/refund-requests", submission(confirmed=False),
                                            headers=self.auth())[0], 400)
        self.assertEqual(self.api.json_call("/api/refund-requests", submission(email="not-an-email"),
                                            headers=self.auth())[0], 400)
        self.assertEqual(self.api.json_call("/api/refund-requests", submission(request_key="not-a-uuid"),
                                            headers=self.auth())[0], 400)
        self.assertEqual(self.api.json_call("/api/refund-requests", {"email": "a@b.example"},
                                            headers=self.auth())[0], 400)

    def test_staff_cannot_use_passenger_endpoints(self):
        staff_token = self.api.login(STAFF, STAFF_PASSWORD)["token"]
        self.assertEqual(self.api.json_call("/api/me", headers=self.auth(staff_token))[0], 403)
        self.assertEqual(self.api.json_call("/api/refund-requests", submission(),
                                            headers=self.auth(staff_token))[0], 403)

    def test_receipt_downloads_the_owners_json(self):
        self.assertEqual(self.api.call("/api/refund-requests/receipt", headers=self.auth())[0], 404)
        _, _, created = self.api.json_call("/api/refund-requests", submission(), headers=self.auth())
        status, headers, raw = self.api.call("/api/refund-requests/receipt", headers=self.auth())
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertEqual(json.loads(raw)["receipt"]["reference"], created["request"]["reference"])

    def test_oversized_and_non_json_bodies_are_rejected(self):
        status, _, _ = self.api.raw("/api/refund-requests", b"x" * (server.MAX_BODY_BYTES + 1),
                                    headers=self.auth())
        self.assertEqual(status, 413)
        self.assertEqual(self.api.raw("/api/refund-requests", b"not json", headers=self.auth())[0], 400)
        self.assertEqual(self.api.raw("/api/refund-requests", b"{}", content_type="text/plain",
                                      headers=self.auth())[0], 415)
        self.assertEqual(self.api.raw("/api/refund-requests", b"", headers=self.auth())[0], 413)

    def test_errors_never_leak_credentials_tokens_or_email_addresses(self):
        secret_email = "private.passenger@example.com"
        bodies = []
        bodies.append(self.api.json_call("/api/auth/login",
                                         {"username": PASSENGER, "password": PASSENGER_PASSWORD + "-x"})[2])
        self.sap.error = server.APIError(503, "SAP_UNAVAILABLE", "SAP is temporarily unavailable.")
        bodies.append(self.api.json_call("/api/refund-requests", submission(email=secret_email),
                                         headers=self.auth())[2])
        self.sap.error = None
        bodies.append(self.api.json_call("/api/refund-requests", submission(email="nope"),
                                         headers=self.auth())[2])
        staff_token = self.api.login(STAFF, STAFF_PASSWORD)["token"]
        bodies.append(self.api.json_call("/api/me", headers=self.auth(staff_token))[2])
        rendered = json.dumps(bodies)
        for secret in (PASSENGER_PASSWORD, STAFF_PASSWORD, self.token, secret_email):
            self.assertNotIn(secret, rendered)


if __name__ == "__main__":
    unittest.main()
