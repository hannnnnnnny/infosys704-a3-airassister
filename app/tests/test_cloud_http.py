"""Cloud API access boundaries and persisted review behavior."""
import importlib.util
import json
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_cloud_store import MemorySnapshots, application


class CloudHTTPTests(unittest.TestCase):
    def test_cloud_handler_is_available(self):
        self.assertIsNotNone(importlib.util.find_spec("cloud_handler"))

    def setUp(self):
        if importlib.util.find_spec("cloud_handler") is None:
            return
        from cloud_handler import make_cloud_handler
        from cloud_store import CloudStore
        import server
        self.env = patch.dict("os.environ", {"VERCEL_URL": "preview.example", "BLOB_READ_WRITE_TOKEN": "test-session-secret"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.store = CloudStore(MemorySnapshots())
        handler = make_cloud_handler(self.store, server.SAPClient(server.SAPConfig()))
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

    def test_api_requires_a_signed_browser_session(self):
        self.assertEqual(self.call("/api/bookings?reference=NZ7K2H&lastname=Taylor")[0], 401)
        status, headers, body = self.call("/")
        self.assertEqual(status, 200)
        cookie = headers["Set-Cookie"]
        for flag in ("HttpOnly", "Secure", "SameSite=Strict"):
            self.assertIn(flag, cookie)
        auth = {"Cookie": cookie.split(";", 1)[0]}
        self.assertEqual(self.call("/api/bookings?reference=NZ7K2H&lastname=Taylor", headers=auth)[0], 200)
        self.assertEqual(self.call("/api/bookings", headers={"Cookie": "airassist_session=forged"})[0], 401)

    def test_host_and_cross_origin_access_are_rejected(self):
        self.assertEqual(self.call("/api/health", headers={"Host": "attacker.example"})[0], 400)
        self.assertEqual(self.call("/api/health", headers={"Origin": "https://attacker.example"})[0], 403)
        self.assertEqual(self.call("/api/health", headers={"Origin": "null"})[0], 403)
        self.assertEqual(self.call("/api/health", headers={"Origin": "https://preview.example"})[0], 200)

    def test_private_sources_are_not_served(self):
        for path in ("/server.py", "/.env", "/README.md", "/%2e%2e/server.py"):
            self.assertEqual(self.call(path)[0], 404)

    def test_cloud_receipt_and_review_survive_new_store(self):
        record, _ = self.store.submit(application())
        _, headers, _ = self.call("/")
        auth = {"Cookie": headers["Set-Cookie"].split(";", 1)[0]}
        query = "?reference=" + record["publicReference"] + "&email=demo%40example.com"
        status, _, body = self.call("/api/review-cases" + query, headers=auth)
        self.assertEqual(status, 200)
        case = json.loads(body)["case"]
        self.assertEqual(case["request"]["publicReference"], record["publicReference"])
        review = {
            "reference": record["publicReference"], "email": record["email"], "version": 0,
            "checks": {"paymentEvidenceReviewed": True, "refundRulesReviewed": True, "supportingDetailsReviewed": False},
            "paymentReference": "DEMO-RECEIPT", "specialistRequired": False,
            "note": "A local prototype note must remain exactly as entered.", "action": "save_review",
        }
        status, _, body = self.call("/api/review-cases", review, auth)
        self.assertEqual(status, 200)
        saved = json.loads(body)["case"]
        self.assertEqual(saved["reviewNote"], review["note"])
        self.assertEqual(saved["version"], 1)
        self.assertEqual(self.call("/api/review-cases", review, auth)[0], 409)
        review.update(version=1, action="handoff", note="Queue the synthetic request.")
        self.assertEqual(self.call("/api/review-cases", review, auth)[0], 200)
        status, _, body = self.call("/api/refund-requests/receipt" + query, headers=auth)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["receipt"]["publicReference"], record["publicReference"])
        self.assertEqual(json.loads(body)["receipt"]["review"]["state"], "queued")


if __name__ == "__main__":
    unittest.main()
