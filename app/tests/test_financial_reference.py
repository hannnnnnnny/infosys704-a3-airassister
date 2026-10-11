"""Mock-upstream checks for documentary case references; no SAP writes or keys."""
import importlib.util
import io
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


SPEC = importlib.util.spec_from_file_location("airassist_reference_test_server", Path(__file__).resolve().parents[1] / "server.py")
server = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = server
SPEC.loader.exec_module(server)

RAW_DOCUMENT = {
    "CreditMemoRequest": "60000002", "TotalNetAmount": "1000.00", "TransactionCurrency": "USD",
    "ReferenceSDDocument": "60000001", "ReferenceSDDocumentCategory": "H",
    "OverallSDProcessStatus": "C", "SalesDocApprovalStatus": "", "CreationDate": "2026-02-05",
}


class MockResponse(io.BytesIO):
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class MockSAPOpener:
    def __init__(self):
        self.value = dict(RAW_DOCUMENT)
        self.error = None
        self.calls = []
        self.during_get = None

    def open(self, request, timeout):
        self.calls.append(request)
        if self.during_get:
            callback, self.during_get = self.during_get, None
            callback()
        if self.error:
            raise self.error
        return MockResponse(json.dumps(self.value).encode())


class FinancialReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="runtime-", dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.public = self.folder / "public"
        self.public.mkdir()
        self.store = server.ApplicationStore(self.folder / "test.sqlite3")
        self.opener = MockSAPOpener()
        config = server.SAPConfig("live", "https://sandbox.api.sap.com/test-service/0001", "test-only-key", "personal")
        self.sap = server.SAPClient(config, self.opener)
        self.httpd = None
        self.start_server()
        self.addCleanup(self.stop_server)
        self.application = {
            "bookingReference": "NZ7K2H", "lastName": "Taylor", "email": "alex@example.com",
            "reason": "flight_cancelled", "details": "Cancelled synthetic journey.",
            "acknowledged": True, "requestKey": str(uuid.uuid4()),
        }
        status, _, result = self.call("/api/refund-requests", self.application)
        self.assertEqual(status, 201, result)
        self.reference = result["request"]["publicReference"]

    def start_server(self):
        self.httpd = server.make_server(self.store, self.sap, public_dir=self.public, port=0)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"

    def stop_server(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.thread.join(timeout=2)
            self.httpd = None

    def call(self, path, body=None):
        request = Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                          headers={"Content-Type": "application/json"} if body is not None else {})
        try:
            response = urlopen(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, json.loads(response.read())

    def case(self):
        status, _, result = self.call("/api/review-cases?" + urlencode({"reference": self.reference, "email": self.application["email"]}))
        self.assertEqual(status, 200, result)
        return result["case"]

    def capture_body(self, case=None, **changes):
        case = case or self.case()
        body = {"reference": self.reference, "email": self.application["email"], "version": case["version"],
                "documentId": "60000002", "note": "Public sandbox example retained for demonstration; no booking match."}
        body.update(changes)
        return body

    def capture(self, body=None, expected=200):
        status, _, result = self.call("/api/review-cases/financial-reference", body or self.capture_body())
        self.assertEqual(status, expected, result)
        return result.get("case") if expected == 200 else result

    def manual_body(self, case, **changes):
        body = {"reference": self.reference, "email": self.application["email"], "version": case["version"],
                "checks": {"paymentEvidenceReviewed": True, "refundRulesReviewed": True, "supportingDetailsReviewed": True},
                "paymentReference": "MANUAL-DEMO-01", "specialistRequired": False,
                "note": "Manual checks are separate from the SAP example.", "action": "save_review"}
        body.update(changes)
        return body

    def test_actual_get_snapshot_is_documentary_and_never_checks_payment_or_readiness(self):
        before = self.case()
        captured = self.capture(self.capture_body(before))
        snapshot = captured["financialReference"]
        self.assertEqual(captured["version"], before["version"] + 1)
        self.assertEqual(snapshot["version"], captured["version"])
        self.assertEqual(snapshot["record"]["totalNetAmount"], 1000.0)
        self.assertEqual(snapshot["record"]["currency"], "USD")
        self.assertEqual((captured["request"]["ticketValue"], captured["request"]["currency"]), (248.0, "NZD"))
        self.assertEqual(snapshot["context"], "demonstration_only")
        self.assertEqual(snapshot["bookingMatch"], "not_verified")
        self.assertEqual(snapshot["paymentVerification"], "not_performed")
        self.assertEqual(snapshot["refundEligibility"], "not_assessed")
        self.assertEqual(snapshot["source"]["mode"], "live")
        self.assertIn("public sandbox", snapshot["source"]["label"])
        self.assertRegex(snapshot["source"]["fetchedAt"], r"Z$")
        self.assertEqual(snapshot["note"], captured["events"][-1]["note"])
        self.assertEqual(captured["events"][-1]["type"], "financial_reference_captured")
        self.assertEqual(captured["request"]["review"]["financialReference"], snapshot)
        for field in ("checks", "paymentReference", "reviewState", "reviewNote", "triage", "checklist"):
            self.assertEqual(captured[field], before[field])
        self.assertEqual(captured["request"]["status"], "submitted")
        self.assertIsNone(captured["request"]["sapCreditMemoRequestId"])
        self.assertEqual(len(self.opener.calls), 1)
        self.assertEqual(self.opener.calls[0].get_method(), "GET")
        self.assertIsNone(self.opener.calls[0].data)
        serialized = json.dumps(snapshot)
        self.assertNotIn("test-only-key", serialized)
        self.assertNotIn("base_url", serialized)

    def test_reference_persists_and_receipt_retry_and_manual_review_keep_the_same_snapshot(self):
        captured = self.capture()
        self.stop_server()
        self.store = server.ApplicationStore(self.folder / "test.sqlite3")
        self.start_server()
        self.assertEqual(self.case(), captured)
        query = urlencode({"reference": self.reference, "email": self.application["email"]})
        status, _, receipt = self.call("/api/refund-requests/receipt?" + query)
        self.assertEqual(status, 200)
        self.assertEqual(receipt["receipt"], captured["request"])
        status, _, repeated = self.call("/api/refund-requests", self.application)
        self.assertEqual(status, 200)
        self.assertFalse(repeated["created"])
        self.assertEqual(repeated["request"], captured["request"])
        status, _, reviewed = self.call("/api/review-cases", self.manual_body(captured))
        self.assertEqual(status, 200, reviewed)
        self.assertEqual(reviewed["case"]["financialReference"], captured["financialReference"])
        self.assertEqual(reviewed["case"]["reviewNote"], "Manual checks are separate from the SAP example.")

    def test_successive_captures_are_append_only_and_do_not_change_manual_currency_or_triage(self):
        status, _, result = self.call("/api/review-cases", self.manual_body(self.case()))
        self.assertEqual(status, 200)
        prepared = result["case"]
        first = self.capture(self.capture_body(prepared))
        self.opener.value = dict(RAW_DOCUMENT, TransactionCurrency="EUR", TotalNetAmount="750.00")
        second = self.capture(self.capture_body(first, note="A second public sandbox snapshot; still not matched."))
        self.assertEqual(second["financialReference"]["record"]["currency"], "EUR")
        for field in ("checks", "triage", "checklist", "paymentReference", "reviewNote", "reviewState"):
            self.assertEqual(second[field], prepared[field])
        with self.store.connect() as connection:
            rows = connection.execute("SELECT captured_record FROM review_financial_references WHERE public_reference=? ORDER BY version", (self.reference,)).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(json.loads(rows[0]["captured_record"]), first["financialReference"])
        self.assertEqual(json.loads(rows[1]["captured_record"]), second["financialReference"])

    def test_wrong_owner_stale_and_queued_are_rejected_before_upstream(self):
        before = self.case()
        self.capture(self.capture_body(before, email="wrong@example.com"), expected=404)
        self.capture(self.capture_body(before, reference="AF-NOTEXIST"), expected=404)
        self.capture(self.capture_body(before, version=before["version"] + 1), expected=409)
        self.assertEqual(self.opener.calls, [])
        status, _, result = self.call("/api/review-cases", self.manual_body(before, action="handoff"))
        self.assertEqual(status, 200)
        queued = result["case"]
        result = self.capture(self.capture_body(queued), expected=409)
        self.assertEqual(result["error"]["code"], "CASE_ALREADY_QUEUED")
        self.assertEqual(self.opener.calls, [])
        self.assertEqual(self.case(), queued)

    def test_version_rechecked_after_upstream_prevents_racing_overwrite(self):
        before = self.case()
        self.opener.during_get = lambda: self.store.update_review(server.validate_review_payload(self.manual_body(before)))
        error = self.capture(self.capture_body(before), expected=409)
        self.assertEqual(error["error"]["code"], "REVIEW_VERSION_CONFLICT")
        current = self.case()
        self.assertEqual(current["version"], before["version"] + 1)
        self.assertIsNone(current["financialReference"])
        self.assertEqual(current["events"][-1]["type"], "review_saved")
        self.assertEqual(len(self.opener.calls), 1)

    def test_failed_upstream_never_creates_reference_or_event_and_retains_existing_reference(self):
        saved = self.capture()
        for upstream, expected in ((401, 401), (403, 403), (404, 404), (429, 503), (503, 503)):
            self.opener.error = HTTPError("https://sandbox.api.sap.com/test", upstream, "private upstream detail", {}, io.BytesIO(b"private payload"))
            error = self.capture(self.capture_body(saved), expected=expected)
            self.assertNotIn("private", json.dumps(error))
            self.assertEqual(self.case(), saved)
        self.opener.error = TimeoutError()
        self.capture(self.capture_body(saved), expected=504)
        self.assertEqual(self.case(), saved)
        self.sap.config = server.SAPConfig()
        calls = len(self.opener.calls)
        self.capture(self.capture_body(saved), expected=503)
        self.assertEqual(len(self.opener.calls), calls)
        self.assertEqual(self.case(), saved)

    def test_owner_pair_is_rechecked_after_upstream_before_snapshot_write(self):
        before = self.case()
        def transfer_test_record():
            # Isolated fixture mutation models ownership changing during the GET.
            with self.store.connect() as connection:
                connection.execute("UPDATE refund_requests SET email=? WHERE public_reference=?",
                                   ("new-owner@example.com", self.reference))
        self.opener.during_get = transfer_test_record
        error = self.capture(self.capture_body(before), expected=404)
        self.assertEqual(error["error"]["code"], "REQUEST_NOT_FOUND")
        self.assertNotIn("new-owner", json.dumps(error))
        unchanged = self.store.get_case(self.reference, "new-owner@example.com")
        self.assertEqual(unchanged["version"], before["version"])
        self.assertEqual(unchanged["events"], before["events"])
        self.assertIsNone(unchanged["financialReference"])

    def test_bad_client_inputs_are_rejected_without_any_upstream_call_or_mutation(self):
        before = self.case()
        inputs = ({"documentId": True}, {"documentId": 60000002}, {"documentId": {}},
                  {"documentId": []}, {"documentId": "6/2"}, {"documentId": "1" * 11},
                  {"documentId": "60\r\n0002"}, {"version": True}, {"version": "0"},
                  {"note": ""}, {"note": "x" * 1001}, {"note": "bad\r\nnote"})
        for changes in inputs:
            with self.subTest(changes=changes):
                self.capture(self.capture_body(before, **changes), expected=400)
        self.assertEqual(self.opener.calls, [])
        self.assertEqual(self.case(), before)

    def test_missing_and_zero_financial_values_are_preserved_without_payment_claims(self):
        self.opener.value = dict(RAW_DOCUMENT)
        self.opener.value.pop("TotalNetAmount")
        self.opener.value.pop("TransactionCurrency")
        first = self.capture()
        self.assertIsNone(first["financialReference"]["record"]["totalNetAmount"])
        self.assertIsNone(first["financialReference"]["record"]["currency"])
        self.opener.value = dict(RAW_DOCUMENT, TotalNetAmount="0.00", SalesDocApprovalStatus="0", OverallSDProcessStatus="0")
        second = self.capture(self.capture_body(first))
        record = second["financialReference"]["record"]
        self.assertEqual((record["totalNetAmount"], record["processStatusCode"], record["approvalStatusCode"]), (0.0, "0", "0"))
        self.assertFalse(second["checks"]["paymentEvidenceReviewed"])
        self.assertFalse(second["triage"]["readyForHandoff"])

    def test_boolean_upstream_amount_is_rejected_before_snapshot_or_case_mutation(self):
        before = self.case()
        for invalid_amount in (True, False):
            with self.subTest(amount=invalid_amount):
                self.opener.value = dict(RAW_DOCUMENT, TotalNetAmount=invalid_amount)
                result = self.capture(self.capture_body(before), expected=502)
                self.assertEqual(result["error"]["code"], "SAP_BAD_RESPONSE")
                self.assertEqual(self.case(), before)
                with self.store.connect() as connection:
                    count = connection.execute("SELECT COUNT(*) FROM review_financial_references WHERE public_reference=?",
                                               (self.reference,)).fetchone()[0]
                self.assertEqual(count, 0)
        self.assertEqual(len(self.opener.calls), 2)

    def test_malformed_upstream_documentary_values_are_not_saved_and_host_label_is_truthful(self):
        before = self.case()
        self.opener.value = dict(RAW_DOCUMENT, TransactionCurrency={"bad": "shape"})
        self.capture(self.capture_body(before), expected=502)
        self.assertEqual(self.case(), before)
        self.opener.value = dict(RAW_DOCUMENT)
        self.sap.config = server.SAPConfig("live", "https://api.sap.com/test-service/0001", "test-only-key", "personal")
        captured = self.capture(self.capture_body(before))
        self.assertNotIn("sandbox", captured["financialReference"]["source"]["label"])
        self.assertNotIn("production", captured["financialReference"]["source"]["label"])


if __name__ == "__main__":
    unittest.main()
