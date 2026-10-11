"""Behavior checks for the downloadable JSON application receipt."""
import importlib.util
import json
import sys
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SPEC = importlib.util.spec_from_file_location("airassist_server", Path(__file__).resolve().parents[1] / "server.py")
server = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = server
SPEC.loader.exec_module(server)
TEST_TEMP_DIR = Path(__file__).resolve().parent


def payload(**changes):
    result = {"bookingReference": "NZ7K2H", "lastName": "Taylor", "email": "alex@example.com",
              "reason": "flight_cancelled", "details": "Cancelled sample flight.",
              "acknowledged": True, "requestKey": str(uuid.uuid4())}
    result.update(changes)
    return result


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="runtime-", dir=TEST_TEMP_DIR)
        folder = Path(self.temp.name)
        public = folder / "public"
        public.mkdir()
        (public / "index.html").write_text("test-public-page", encoding="utf-8")
        self.httpd = server.make_server(server.ApplicationStore(folder / "data.sqlite3"), server.SAPClient(server.SAPConfig()), public_dir=public, port=0)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def call(self, path, body=None, headers=None):
        request_headers = {"Content-Type": "application/json"} if body is not None else {}
        request_headers.update(headers or {})
        request = Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                          headers=request_headers)
        try:
            response = urlopen(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, response.read()

    def submit(self, **changes):
        status, _, raw = self.call("/api/refund-requests", payload(**changes))
        self.assertEqual(status, 201)
        return json.loads(raw)["request"]

    def test_receipt_downloads_json_for_matching_owner(self):
        record = self.submit()
        query = urlencode({"reference": record["publicReference"], "email": record["email"]})
        status, headers, raw = self.call("/api/refund-requests/receipt?" + query)
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers["Content-Type"])
        disposition = headers["Content-Disposition"]
        self.assertTrue(disposition.startswith("attachment; filename="))
        self.assertIn(record["publicReference"], disposition)
        self.assertIn(".json", disposition)
        body = json.loads(raw)
        self.assertEqual(body["format"], "airassist-application-receipt")
        self.assertEqual(body["receipt"], record)
        self.assertNotIn("requestKey", body["receipt"])
        self.assertEqual(body["receipt"]["source"]["mode"], "local")
        self.assertIsNone(body["receipt"]["sapCreditMemoRequestId"])

    def test_receipt_is_case_insensitive_for_owner_lookup(self):
        record = self.submit()
        query = urlencode({"reference": record["publicReference"].lower(), "email": record["email"].upper()})
        status, _, raw = self.call("/api/refund-requests/receipt?" + query)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["receipt"]["publicReference"], record["publicReference"])

    def test_receipt_hides_unknown_or_wrong_owner_application(self):
        record = self.submit()
        for reference, email in ((record["publicReference"], "wrong@example.com"), ("AF-NOTEXIST", record["email"])):
            with self.subTest(reference=reference, email=email):
                status, headers, raw = self.call("/api/refund-requests/receipt?" + urlencode({"reference": reference, "email": email}))
                self.assertEqual(status, 404)
                self.assertNotIn("Content-Disposition", headers)
                self.assertEqual(json.loads(raw)["error"]["code"], "REQUEST_NOT_FOUND")

    def test_receipt_rejects_bad_parameters_and_wrong_method(self):
        record = self.submit()
        doubled = "reference=" + record["publicReference"] + "&reference=" + record["publicReference"] + "&email=" + record["email"]
        self.assertEqual(self.call("/api/refund-requests/receipt?" + doubled)[0], 400)
        self.assertEqual(self.call("/api/refund-requests/receipt?reference=" + record["publicReference"])[0], 400)
        self.assertEqual(self.call("/api/refund-requests/receipt?reference=" + record["publicReference"] + "&email=not-an-email")[0], 400)
        self.assertEqual(self.call("/api/refund-requests/receipt", {"reference": record["publicReference"]})[0], 405)


if __name__ == "__main__":
    unittest.main()
