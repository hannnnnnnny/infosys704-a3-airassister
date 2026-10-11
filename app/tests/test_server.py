"""Behavior checks for persistent applications and truthful, read-only SAP access."""
import concurrent.futures
import gzip
import importlib.util
import io
import json
import sys
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
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


class ApplicationBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="runtime-", dir=TEST_TEMP_DIR)
        self.path = Path(self.temp.name) / "applications.sqlite3"
        self.store = server.ApplicationStore(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_saved_request_survives_new_store_and_never_claims_sap_creation(self):
        record, created = self.store.submit(server.validate_application(payload()))
        self.assertTrue(created)
        stored = server.ApplicationStore(self.path).find(record["publicReference"], "ALEX@example.com")
        self.assertEqual(record, stored)
        self.assertRegex(record["publicReference"], r"^AF-[0-9A-F]{12}$")
        self.assertEqual(record["status"], "submitted")
        self.assertIsNone(record["sapCreditMemoRequestId"])
        self.assertEqual(record["source"]["mode"], "local")
        self.assertEqual((record["ticketValue"], record["currency"]), (248.0, "NZD"))

    def test_retry_and_new_key_deduplicate_but_key_reuse_conflicts(self):
        original = payload()
        application = server.validate_application(original)
        first, _ = self.store.submit(application)
        retry, created = self.store.submit(application)
        self.assertFalse(created)
        self.assertEqual(first, retry)
        duplicate = server.validate_application(payload(details="Changed details."))
        another, created = self.store.submit(duplicate)
        self.assertFalse(created)
        self.assertEqual(first, another)
        for key in (original["requestKey"], duplicate["requestKey"]):
            with self.assertRaises(server.APIError) as error:
                self.store.submit(server.validate_application(payload(requestKey=key, email="another@example.com")))
            self.assertEqual(error.exception.status, 409)

    def test_concurrent_submissions_create_one_application(self):
        applications = [server.validate_application(payload()) for _ in range(8)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(self.store.submit, applications))
        self.assertEqual(sum(created for _, created in results), 1)
        self.assertEqual(len({record["publicReference"] for record, _ in results}), 1)

    def test_wrong_owner_and_missing_reference_do_not_disclose_an_application(self):
        record, _ = self.store.submit(server.validate_application(payload()))
        for reference, email in ((record["publicReference"], "wrong@example.com"), ("AF-NOTEXIST", "alex@example.com")):
            with self.assertRaises(server.APIError) as error:
                self.store.find(reference, email)
            self.assertEqual((error.exception.status, error.exception.code), (404, "REQUEST_NOT_FOUND"))
            self.assertEqual(error.exception.message, "No application matches these details.")

    def test_application_validation_blocks_agent_booking_and_bad_input(self):
        cases = [(payload(bookingReference="NZ8T3H"), 403), (payload(lastName="Someone"), 404),
                 (payload(acknowledged=False), 400), (payload(acknowledged=1), 400),
                 (payload(email="not-an-email"), 400), (payload(reason="automatically_approve"), 400),
                 (payload(details="x" * 2001), 400), (payload(requestKey="not-a-uuid"), 400)]
        for case, status in cases:
            with self.subTest(case=case):
                with self.assertRaises(server.APIError) as error:
                    server.validate_application(case)
                self.assertEqual(error.exception.status, status)


SAP_RAW = {"CreditMemoRequest": "60000002", "TotalNetAmount": "1000.00", "TransactionCurrency": "USD",
           "ReferenceSDDocument": "60000001", "ReferenceSDDocumentCategory": "H",
           "OverallSDProcessStatus": "C", "CreditMemoReqApprovalStatus": "", "CreationDate": "2026-02-05"}


class FakeResponse(io.BytesIO):
    def __init__(self, value, headers=None):
        super().__init__(value)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class FakeOpener:
    def __init__(self, value=None, error=None, headers=None):
        self.value, self.error, self.calls = value, error, []
        self.headers = headers or {}

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if self.error:
            raise self.error
        value = json.dumps(self.value).encode() if not isinstance(self.value, bytes) else self.value
        return FakeResponse(value, self.headers)


class SAPBoundaryTests(unittest.TestCase):
    def configured(self, opener):
        return server.SAPClient(server.SAPConfig("live", "https://sandbox.api.sap.com/test-service/0001", "test-only-key", "personal"), opener)

    def test_unconfigured_or_nonpersonal_config_never_calls_upstream(self):
        for config in (server.SAPConfig(), server.SAPConfig("live", "https://sandbox.api.sap.com/test/0001", "test-only-key", "classroom"),
                       server.SAPConfig("live", "http://sandbox.api.sap.com/test/0001", "test-only-key"),
                       server.SAPConfig("live", "https://sandbox.api.sap.com.evil.example/test/0001", "test-only-key")):
            opener = FakeOpener(SAP_RAW)
            with self.assertRaises(server.APIError) as error:
                server.SAPClient(config, opener).get_credit_memo("60000002")
            self.assertEqual(error.exception.status, 503)
            self.assertEqual(opener.calls, [])

    def test_live_get_preserves_financial_reference_and_no_payment_mapping(self):
        for value in (SAP_RAW, {"value": [SAP_RAW]}):
            opener = FakeOpener(value)
            record = self.configured(opener).get_credit_memo("60000002")
            request, timeout = opener.calls[0]
            self.assertEqual(request.get_method(), "GET")
            self.assertIsNone(request.data)
            self.assertEqual(timeout, 12)
            self.assertEqual(request.full_url, "https://sandbox.api.sap.com/test-service/0001/CreditMemoRequest/60000002")
            self.assertEqual((record["totalNetAmount"], record["currency"]), (1000.0, "USD"))
            self.assertEqual(record["approvalStatusCode"], "")
            self.assertEqual(record["source"]["mode"], "live")
            self.assertNotIn("paidAmount", record)
            self.assertNotIn("refundedAmount", record)
        self.assertEqual(self.configured(FakeOpener(dict(SAP_RAW, SalesDocApprovalStatus=""))).get_credit_memo("60000002")["approvalStatusCode"], "")

    def test_sap_errors_keep_distinct_status_and_never_return_fake_record(self):
        for upstream, expected in ((401, 401), (403, 403), (404, 404), (429, 503), (503, 503)):
            opener = FakeOpener(error=HTTPError("https://sandbox.api.sap.com/test", upstream, "secret-upstream-message", {}, io.BytesIO(b"private-response")))
            with self.assertRaises(server.APIError) as error:
                self.configured(opener).get_credit_memo("60000002")
            self.assertEqual(error.exception.status, expected)
            self.assertNotIn("secret-upstream-message", error.exception.message)
            self.assertNotIn("private-response", error.exception.message)
        for upstream_error, expected in ((TimeoutError(), 504), (URLError("private-network-detail"), 503)):
            with self.assertRaises(server.APIError) as error:
                self.configured(FakeOpener(error=upstream_error)).get_credit_memo("60000002")
            self.assertEqual(error.exception.status, expected)

    def test_malformed_wrong_id_or_excessive_response_is_rejected(self):
        for value, expected in ((b"<html>login</html>", 502), ({"CreditMemoRequest": "60000001"}, 502),
                                ({"value": []}, 404), (dict(SAP_RAW, TotalNetAmount="NaN"), 502),
                                (b" " * (server.MAX_SAP_BYTES + 1), 502)):
            with self.assertRaises(server.APIError) as error:
                self.configured(FakeOpener(value)).get_credit_memo("60000002")
            self.assertEqual(error.exception.status, expected)

    def test_missing_sap_amount_or_currency_stays_unknown(self):
        raw = dict(SAP_RAW)
        raw.pop("TotalNetAmount")
        raw.pop("TransactionCurrency")
        record = self.configured(FakeOpener(raw)).get_credit_memo("60000002")
        self.assertIsNone(record["totalNetAmount"])
        self.assertIsNone(record["currency"])
        self.assertNotIn("ticketValue", record)

    def test_gzip_sap_json_preserves_reference_amount_and_raw_statuses(self):
        raw = dict(SAP_RAW, SalesDocApprovalStatus="")
        opener = FakeOpener(gzip.compress(json.dumps(raw).encode()), headers={"Content-Encoding": "gzip"})
        record = self.configured(opener).get_credit_memo("60000002")
        self.assertEqual((record["id"], record["totalNetAmount"], record["currency"]), ("60000002", 1000.0, "USD"))
        self.assertEqual((record["processStatusCode"], record["approvalStatusCode"]), ("C", ""))
        self.assertEqual(record["referenceDocument"], "60000001")
        self.assertEqual(record["source"]["mode"], "live")

    def test_gzip_bomb_and_malformed_compressed_response_are_rejected(self):
        valid = gzip.compress(json.dumps(SAP_RAW).encode())
        bomb = gzip.compress(b"x" * (server.MAX_SAP_BYTES + 1))
        for raw in (bomb, valid[:-8], b"not a gzip stream"):
            with self.subTest(compressed_bytes=len(raw)):
                with self.assertRaises(server.APIError) as error:
                    self.configured(FakeOpener(raw, headers={"Content-Encoding": "gzip"})).get_credit_memo("60000002")
                self.assertEqual((error.exception.status, error.exception.code), (502, "SAP_BAD_RESPONSE"))


class HTTPContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="runtime-", dir=TEST_TEMP_DIR)
        folder = Path(self.temp.name)
        public = folder / "public"
        public.mkdir()
        (public / "index.html").write_text("test-public-page", encoding="utf-8")
        (folder / ".env").write_text("private-value", encoding="utf-8")
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

    def test_http_submission_tracking_and_unconfigured_sap(self):
        status, headers, raw = self.call("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["sap"], {"mode": "unconfigured", "configured": False, "accountPolicy": "personal-only"})
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        status, _, raw = self.call("/api/bookings?reference=NZ7K2H&lastname=Taylor")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["booking"]["source"]["mode"], "synthetic")
        status, _, raw = self.call("/api/refund-requests", payload())
        self.assertEqual(status, 201)
        self.assertTrue(json.loads(raw)["created"])
        reference = json.loads(raw)["request"]["publicReference"]
        status, _, raw = self.call("/api/refund-requests?" + urlencode({"reference": reference, "email": "alex@example.com"}))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["request"]["publicReference"], reference)
        status, _, _ = self.call("/api/refund-requests?" + urlencode({"reference": reference, "email": "wrong@example.com"}))
        self.assertEqual(status, 404)
        status, _, raw = self.call("/api/sap/credit-memo-requests?id=60000002")
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(raw)["error"]["code"], "SAP_UNCONFIGURED")
        self.assertNotIn("record", json.loads(raw))

    def test_changed_duplicate_submission_explicitly_returns_original_unchanged(self):
        original = payload()
        status, _, raw = self.call("/api/refund-requests", original)
        original_record = json.loads(raw)["request"]
        self.assertEqual(status, 201)
        changed = payload(reason="schedule_changed", details="New details should not overwrite the original.")
        status, _, raw = self.call("/api/refund-requests", changed)
        result = json.loads(raw)
        self.assertEqual(status, 200)
        self.assertFalse(result["created"])
        self.assertEqual(result["request"], original_record)
        self.assertIn("returned unchanged", result["message"])
        status, _, raw = self.call("/api/refund-requests", original)
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(raw)["created"])

    def test_private_paths_query_pollution_and_sap_post_are_blocked(self):
        for path in ("/../.env", "/%2e%2e/.env", "/..%5c.env", "/%00", "/.env", "/server.py", "/data.sqlite3"):
            self.assertEqual(self.call(path)[0], 404)
        self.assertEqual(self.call("/api/bookings?reference=NZ7K2H&reference=NZ8T3H&lastname=Taylor")[0], 400)
        self.assertEqual(self.call("/api/sap/credit-memo-requests", {"id": "60000002"})[0], 405)

    def test_local_host_and_origin_block_other_websites(self):
        self.assertEqual(self.call("/api/health", headers={"Host": "attacker.example"})[0], 400)
        self.assertEqual(self.call("/api/health", headers={"Origin": "https://attacker.example"})[0], 403)
        self.assertEqual(self.call("/api/refund-requests", payload(), {"Origin": "null"})[0], 403)
        self.assertEqual(self.call("/api/refund-requests", payload(), {"Origin": self.base})[0], 201)


if __name__ == "__main__":
    unittest.main()
