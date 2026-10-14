"""Cloud API access boundaries and the persisted refund flow."""
import importlib.util
import json
import threading
import unittest
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from refund_support import (PASSENGER, PASSENGER_PASSWORD, STAFF, STAFF_PASSWORD,
                            FakeSAP, make_auth, server)
from test_cloud_store import MemorySnapshots


def submission(email="mark.don@example.com"):
    return {"email": email, "confirmed": True, "requestKey": str(uuid.uuid4())}


class CloudHTTPTests(unittest.TestCase):
    def test_cloud_handler_is_available(self):
        self.assertIsNotNone(importlib.util.find_spec("cloud_handler"))

    def setUp(self):
        if importlib.util.find_spec("cloud_handler") is None:
            return
        from cloud_handler import make_cloud_handler
        from cloud_store import CloudStore
        self.env = patch.dict("os.environ", {"VERCEL_URL": "preview.example",
                                             "BLOB_READ_WRITE_TOKEN": "test-blob-token"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.sap = FakeSAP()
        self.store = CloudStore(MemorySnapshots())
        handler = make_cloud_handler(self.store, self.sap, make_auth(deployed=True))
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()

    def call(self, path, payload=None, headers=None):
        headers = {"Host": "preview.example", **(headers or {})}
        data = None if payload is None else json.dumps(payload).encode()
        if payload is not None:
            headers["Content-Type"] = "application/json"
        try:
            response = urlopen(Request(self.base + path, data=data, headers=headers))
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, response.read()

    def session(self):
        status, headers, _ = self.call("/")
        self.assertEqual(status, 200)
        cookie = headers["Set-Cookie"]
        return {"Cookie": cookie.split(";", 1)[0]}, cookie

    def sign_in(self, username, password):
        cookie_headers, _ = self.session()
        status, _, body = self.call("/api/auth/login", {"username": username, "password": password},
                                    headers=cookie_headers)
        self.assertEqual(status, 200)
        return {**cookie_headers, "Authorization": "Bearer " + json.loads(body)["token"]}

    def test_api_requires_a_signed_browser_session(self):
        self.assertEqual(self.call("/api/me")[0], 401)
        self.assertEqual(self.call("/api/staff/requests")[0], 401)
        self.assertEqual(self.call("/api/auth/login", {"username": STAFF, "password": STAFF_PASSWORD})[0], 401)
        _, cookie = self.session()
        for flag in ("HttpOnly", "Secure", "SameSite=Strict"):
            self.assertIn(flag, cookie)
        self.assertEqual(self.call("/api/me", headers={"Cookie": "airassist_session=forged"})[0], 401)

    def test_host_and_cross_origin_access_are_rejected(self):
        self.assertEqual(self.call("/api/health", headers={"Host": "attacker.example"})[0], 400)
        self.assertEqual(self.call("/api/health", headers={"Origin": "https://attacker.example"})[0], 403)
        self.assertEqual(self.call("/api/health", headers={"Origin": "null"})[0], 403)
        self.assertEqual(self.call("/api/health", headers={"Origin": "https://preview.example"})[0], 200)

    def test_private_sources_are_not_served(self):
        for path in ("/server.py", "/.env", "/README.md", "/%2e%2e/server.py"):
            self.assertEqual(self.call(path)[0], 404)

    def test_removed_frontend_helper_is_not_served(self):
        self.assertEqual(self.call("/workflow-state.js")[0], 404)

    def test_passenger_to_staff_flow_survives_new_store(self):
        passenger = self.sign_in(PASSENGER, PASSENGER_PASSWORD)
        status, _, body = self.call("/api/me", headers=passenger)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["booking"]["reference"], "NZ7K2H")
        status, _, body = self.call("/api/refund-requests", submission(), headers=passenger)
        self.assertEqual(status, 201)
        reference = json.loads(body)["request"]["reference"]
        staff = self.sign_in(STAFF, STAFF_PASSWORD)
        status, _, body = self.call("/api/staff/requests", headers=staff)
        self.assertEqual(status, 200)
        references = [record["reference"] for record in json.loads(body)["requests"]]
        self.assertIn(reference, references)
        self.assertIn("AF-DEMO000001", references)
        decision = {"decision": "approve", "note": "", "version": 1}
        status, _, body = self.call("/api/staff/requests/" + reference + "/decision", decision, headers=staff)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["request"]["status"], "approved")
        # The decision is visible through a brand new store instance.
        self.assertEqual(self.store.request_for_booking("NZ7K2H")["status"], "approved")


if __name__ == "__main__":
    unittest.main()
