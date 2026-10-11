"""Behavior checks for the local review-case preparation workflow."""
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


def review_body(record, **changes):
    result = {
        "reference": record["publicReference"], "email": record["email"], "version": 0,
        "checks": {"paymentEvidenceReviewed": True, "refundRulesReviewed": True, "supportingDetailsReviewed": True},
        "paymentReference": "PAY-123", "specialistRequired": False,
        "note": "Local review note.", "action": "save_review",
    }
    result.update(changes)
    return result


class CaseWorkflowHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="runtime-", dir=TEST_TEMP_DIR)
        folder = Path(self.temp.name)
        public = folder / "public"
        public.mkdir()
        (public / "index.html").write_text("test-public-page", encoding="utf-8")
        self.db_path = folder / "data.sqlite3"
        self.httpd = server.make_server(server.ApplicationStore(self.db_path), server.SAPClient(server.SAPConfig()), public_dir=public, port=0)
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

    def get_case(self, record, email=None):
        status, _, raw = self.call("/api/review-cases?" + urlencode({"reference": record["publicReference"], "email": email or record["email"]}))
        self.assertEqual(status, 200)
        return json.loads(raw)["case"]

    def test_initial_state_is_missing_and_not_started(self):
        record = self.submit(details="")
        case = self.get_case(record)
        self.assertEqual(case["version"], 0)
        self.assertEqual(case["reviewState"], "not_started")
        self.assertEqual(case["checks"], {"paymentEvidenceReviewed": False, "refundRulesReviewed": False, "supportingDetailsReviewed": False})
        self.assertEqual(case["paymentReference"], "")
        self.assertFalse(case["specialistRequired"])
        self.assertEqual(case["reviewNote"], "")
        self.assertEqual(case["request"]["status"], "submitted")
        self.assertEqual(case["request"]["statusLabel"], "Received · awaiting review")
        self.assertEqual(case["request"]["updatedAt"], case["request"]["createdAt"])
        self.assertEqual(case["triage"]["route"], "information_needed")
        self.assertFalse(case["triage"]["readyForHandoff"])
        self.assertIn("Payment evidence review", case["request"]["review"]["missingItems"])
        checklist = {item["id"]: item for item in case["checklist"]}
        self.assertEqual(checklist["booking"]["status"], "available")
        self.assertEqual(checklist["contact"]["status"], "available")
        self.assertEqual(checklist["payment"]["status"], "missing")
        self.assertEqual(checklist["rules"]["status"], "missing")
        self.assertEqual(checklist["supporting"]["status"], "not_required")
        self.assertFalse(checklist["supporting"]["required"])
        self.assertEqual([event["type"] for event in case["events"]], ["submitted"])
        self.assertEqual(case["events"][0]["at"], case["request"]["createdAt"])
        self.assertEqual(case["events"][0]["version"], 0)
        self.assertEqual(case["request"]["review"]["events"], case["events"])

    def test_supporting_required_for_other_reason_or_details(self):
        record = self.submit(reason="other", details="")
        case = self.get_case(record)
        checklist = {item["id"]: item for item in case["checklist"]}
        self.assertTrue(checklist["supporting"]["required"])
        self.assertEqual(checklist["supporting"]["status"], "missing")
        record2 = self.submit(reason="flight_cancelled", details="  ", requestKey=str(uuid.uuid4()), email="sam@example.com")
        case2 = self.get_case(record2, email="sam@example.com")
        self.assertFalse({item["id"]: item for item in case2["checklist"]}["supporting"]["required"])

    def test_standard_handoff_persists_across_store_reopen_and_receipt(self):
        record = self.submit()
        status, _, raw = self.call("/api/review-cases", review_body(record, action="save_review"))
        self.assertEqual(status, 200)
        saved = json.loads(raw)["case"]
        self.assertEqual(saved["reviewState"], "prepared")
        self.assertEqual(saved["version"], 1)
        self.assertEqual(saved["request"]["status"], "review_prepared")
        self.assertEqual(saved["request"]["statusLabel"], "Prepared · local review")
        self.assertEqual(saved["triage"]["route"], "standard")
        self.assertEqual([event["type"] for event in saved["events"]], ["submitted", "review_saved"])
        status, _, raw = self.call("/api/review-cases", review_body(record, version=1, action="handoff"))
        self.assertEqual(status, 200)
        queued = json.loads(raw)["case"]
        self.assertEqual(queued["reviewState"], "queued")
        self.assertEqual(queued["version"], 2)
        self.assertEqual(queued["request"]["status"], "queued_for_review")
        self.assertEqual(queued["request"]["statusLabel"], "Queued · local review")
        self.assertEqual(queued["triage"]["route"], "standard")
        self.assertEqual(queued["events"][-1]["type"], "handoff")
        self.assertEqual(queued["events"][-1]["route"], "standard")
        self.assertEqual(queued["events"][-1]["queue"], "Standard review")
        case_again = self.get_case(record)
        self.assertEqual(case_again, queued)
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        self.httpd = server.make_server(server.ApplicationStore(self.db_path), server.SAPClient(server.SAPConfig()), public_dir=Path(self.temp.name) / "public", port=0)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"
        reopened_store = self.get_case(record)
        self.assertEqual(reopened_store, queued)
        status, _, raw = self.call("/api/refund-requests?" + urlencode({"reference": record["publicReference"], "email": record["email"]}))
        self.assertEqual(json.loads(raw)["request"], queued["request"])
        status, _, raw = self.call("/api/refund-requests/receipt?" + urlencode({"reference": record["publicReference"], "email": record["email"]}))
        self.assertEqual(json.loads(raw)["receipt"], queued["request"])

    def test_other_reason_routes_complex_with_specialist_queue(self):
        record = self.submit(reason="other", details="Need manual review.")
        status, _, raw = self.call("/api/review-cases", review_body(record, action="handoff"))
        self.assertEqual(status, 200)
        case = json.loads(raw)["case"]
        self.assertEqual(case["triage"]["route"], "complex")
        self.assertEqual(case["triage"]["label"], "Complex review")
        self.assertEqual(case["triage"]["queue"], "Specialist review")
        self.assertEqual(case["triage"]["ownerRole"], "Refund specialist")
        self.assertTrue(case["triage"]["readyForHandoff"])

    def test_specialist_flag_routes_complex_even_for_standard_reason(self):
        record = self.submit()
        status, _, raw = self.call("/api/review-cases", review_body(record, specialistRequired=True, action="handoff"))
        self.assertEqual(status, 200)
        case = json.loads(raw)["case"]
        self.assertEqual(case["triage"]["route"], "complex")
        self.assertTrue(case["specialistRequired"])

    def test_handoff_with_missing_checks_is_incomplete_and_does_not_mutate(self):
        record = self.submit()
        body = review_body(record, action="handoff", checks={"paymentEvidenceReviewed": False, "refundRulesReviewed": True, "supportingDetailsReviewed": False})
        status, _, raw = self.call("/api/review-cases", body)
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(raw)["error"]["code"], "INCOMPLETE_CASE")
        before = self.get_case(record)
        self.assertEqual(before["version"], 0)
        self.assertEqual(before["reviewState"], "not_started")
        self.assertEqual([event["type"] for event in before["events"]], ["submitted"])

    def test_stale_version_and_wrong_owner_do_not_mutate(self):
        record = self.submit()
        self.call("/api/review-cases", review_body(record, action="save_review"))
        status, _, raw = self.call("/api/review-cases", review_body(record, version=0, action="save_review"))
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(raw)["error"]["code"], "REVIEW_VERSION_CONFLICT")
        case = self.get_case(record)
        self.assertEqual(case["version"], 1)
        self.assertEqual([event["type"] for event in case["events"]], ["submitted", "review_saved"])
        status, _, raw = self.call("/api/review-cases", review_body(record, email="wrong@example.com"))
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(raw)["error"]["code"], "REQUEST_NOT_FOUND")

    def test_queued_case_rejects_save_and_handoff_until_reopened(self):
        record = self.submit()
        self.call("/api/review-cases", review_body(record, action="handoff"))
        for action in ("save_review", "handoff"):
            status, _, raw = self.call("/api/review-cases", review_body(record, version=1, action=action))
            self.assertEqual(status, 409)
            self.assertEqual(json.loads(raw)["error"]["code"], "CASE_ALREADY_QUEUED")
        status, _, raw = self.call("/api/review-cases", review_body(record, version=1, action="save_review"))
        self.assertEqual(status, 409)
        status, _, raw = self.call("/api/review-cases", review_body(record, version=1, action="reopen",
                                                                    checks={"paymentEvidenceReviewed": False, "refundRulesReviewed": True, "supportingDetailsReviewed": False}))
        self.assertEqual(status, 200)
        case = json.loads(raw)["case"]
        self.assertEqual(case["reviewState"], "prepared")
        self.assertEqual(case["version"], 2)
        self.assertEqual(case["request"]["status"], "information_needed")
        self.assertEqual(case["request"]["statusLabel"], "Information needed · local review")
        self.assertEqual(case["events"][-1]["type"], "reopened")
        status, _, raw = self.call("/api/review-cases", review_body(record, version=2, action="save_review",
                                                                    checks={"paymentEvidenceReviewed": True, "refundRulesReviewed": True, "supportingDetailsReviewed": True}))
        self.assertEqual(status, 200)
        case = json.loads(raw)["case"]
        self.assertEqual(case["reviewState"], "prepared")
        self.assertEqual(case["request"]["status"], "review_prepared")

    def test_reopen_rejected_when_not_queued(self):
        record = self.submit()
        status, _, raw = self.call("/api/review-cases", review_body(record, action="reopen"))
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(raw)["error"]["code"], "INVALID_REVIEW_STATE")

    def test_invalid_review_payloads_are_rejected(self):
        record = self.submit()
        cases = [
            review_body(record, version=True),
            review_body(record, version="1"),
            review_body(record, checks={"paymentEvidenceReviewed": "yes", "refundRulesReviewed": True, "supportingDetailsReviewed": True}),
            review_body(record, checks={"paymentEvidenceReviewed": True, "refundRulesReviewed": True}),
            review_body(record, action="approve"),
            review_body(record, note=""),
            review_body(record, note="x" * 1001),
            review_body(record, paymentReference="", checks={"paymentEvidenceReviewed": True, "refundRulesReviewed": True, "supportingDetailsReviewed": True}),
            review_body(record, paymentReference="p" * 81),
            review_body(record, specialistRequired="no"),
        ]
        for body in cases:
            with self.subTest(body=body):
                status, _, raw = self.call("/api/review-cases", body)
                self.assertEqual(status, 400)
                self.assertEqual(json.loads(raw)["error"]["code"], "INVALID_INPUT")
        case = self.get_case(record)
        self.assertEqual(case["version"], 0)
        self.assertEqual(case["reviewState"], "not_started")

    def test_missing_fields_are_rejected(self):
        record = self.submit()
        for missing in ("version", "checks", "note", "action", "email", "reference"):
            body = review_body(record)
            del body[missing]
            with self.subTest(missing=missing):
                status, _, raw = self.call("/api/review-cases", body)
                self.assertEqual(status, 400)
                self.assertEqual(json.loads(raw)["error"]["code"], "INVALID_INPUT")


if __name__ == "__main__":
    unittest.main()
