"""Behavior checks for the read-only SAP boundary and the HTTP access contract."""
import gzip
import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError

from refund_support import APIServer, FakeSAP, make_auth, public_dir, server

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
        self.temp = tempfile.TemporaryDirectory(prefix="runtime-", dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        folder = Path(self.temp.name)
        public = public_dir(folder)
        (folder / ".env").write_text("private-value", encoding="utf-8")
        self.api = APIServer(server.ApplicationStore(folder / "data.sqlite3"), FakeSAP(), public, make_auth())
        self.addCleanup(self.api.close)

    def test_health_static_and_private_paths(self):
        status, headers, raw = self.api.call("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["sap"], {"mode": "unconfigured", "configured": False, "accountPolicy": "personal-only"})
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        status, _, body = self.api.call("/")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"test-public-page")
        for path in ("/../.env", "/%2e%2e/.env", "/..%5c.env", "/%00", "/.env", "/server.py", "/data.sqlite3"):
            self.assertEqual(self.api.call(path)[0], 404, path)

    def test_local_host_and_origin_block_other_websites(self):
        self.assertEqual(self.api.call("/api/health", headers={"Host": "attacker.example"})[0], 400)
        self.assertEqual(self.api.call("/api/health", headers={"Origin": "https://attacker.example"})[0], 403)
        self.assertEqual(self.api.json_call("/api/auth/login", {"username": "admin", "password": "x"},
                                            headers={"Origin": "null"})[0], 403)

    def test_query_pollution_and_unknown_endpoints_are_rejected(self):
        self.assertEqual(self.api.call("/api/health?x=1&x=2")[0], 400)
        self.assertEqual(self.api.call("/api/does-not-exist")[0], 404)
        self.assertEqual(self.api.call("/api/me", method="POST")[0], 405)
        self.assertEqual(self.api.call("/api/staff/requests", method="DELETE")[0], 405)


if __name__ == "__main__":
    unittest.main()
