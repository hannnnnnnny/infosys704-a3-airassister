"""Independent behavior checks for the persisted local review-case contract.

Each test starts from the original application schema in an isolated directory.
No personal configuration, existing application database, or SAP account is read.
"""
import concurrent.futures
import hashlib
import importlib.util
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SPEC = importlib.util.spec_from_file_location("airassist_case_test_server", Path(__file__).resolve().parents[1] / "server.py")
server = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = server
SPEC.loader.exec_module(server)
TEST_TEMP_DIR = Path(__file__).resolve().parent
REFERENCE = "AF-000000000001"
EMAIL = "alex@example.com"
REQUEST_KEY = "00000000-0000-4000-8000-000000000001"


class ForbiddenSAP:
    config = server.SAPConfig()

    def __init__(self):
        self.calls = 0

    def get_credit_memo(self, identifier):
        self.calls += 1
        raise AssertionError("Local case review must not call SAP.")


class ReviewCaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="runtime-", dir=TEST_TEMP_DIR)
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.database = self.folder / "legacy.sqlite3"
        self.public = self.folder / "public"
        self.public.mkdir()
        (self.public / "index.html").write_text("isolated case test", encoding="utf-8")
        self.legacy_payload = {
            "bookingReference": "NZ7K2H", "lastName": "Taylor", "email": EMAIL,
            "reason": "flight_cancelled", "details": "Cancelled sample flight.",
            "acknowledged": True, "requestKey": REQUEST_KEY,
        }
        # The original persisted fingerprint includes normalized booking metadata.
        legacy_fingerprint_fields = {
            name: value for name, value in self.legacy_payload.items()
            if name not in {"acknowledged", "requestKey"}
        }
        legacy_fingerprint_fields.update(ticketValue=248.0, currency="NZD")
        fingerprint = hashlib.sha256(json.dumps(
            legacy_fingerprint_fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode()).hexdigest()
        with sqlite3.connect(self.database) as connection:
            connection.executescript("""
                CREATE TABLE refund_requests (
                    public_reference TEXT PRIMARY KEY, booking_reference TEXT NOT NULL,
                    last_name TEXT NOT NULL, email TEXT NOT NULL, reason TEXT NOT NULL,
                    details TEXT NOT NULL, created_at TEXT NOT NULL, ticket_value REAL NOT NULL,
                    currency TEXT NOT NULL, UNIQUE(booking_reference, email)
                );
                CREATE TABLE submission_keys (
                    request_key TEXT PRIMARY KEY, payload_hash TEXT NOT NULL,
                    public_reference TEXT NOT NULL REFERENCES refund_requests(public_reference)
                );
            """)
            connection.execute("INSERT INTO refund_requests VALUES (?,?,?,?,?,?,?,?,?)", (
                REFERENCE, "NZ7K2H", "Taylor", EMAIL, "flight_cancelled",
                "Cancelled sample flight.", "2026-10-07T00:00:00Z", 248.0, "NZD",
            ))
            connection.execute("INSERT INTO submission_keys VALUES (?,?,?)", (REQUEST_KEY, fingerprint, REFERENCE))
        connection.close()
        self.sap = ForbiddenSAP()
        self.httpd = None
        self.start_server()
        self.addCleanup(self.stop_server)

    def start_server(self):
        self.httpd = server.make_server(server.ApplicationStore(self.database), self.sap, public_dir=self.public, port=0)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"

    def stop_server(self):
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.thread.join(timeout=2)
            self.httpd = None

    def call(self, path, payload=None):
        request = Request(self.base + path, data=json.dumps(payload).encode() if payload is not None else None,
                          headers={"Content-Type": "application/json"} if payload is not None else {})
        try:
            response = urlopen(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, json.loads(response.read())

    def get_case(self, reference=REFERENCE, email=EMAIL):
        status, _, result = self.call("/api/review-cases?" + urlencode({"reference": reference, "email": email}))
        self.assertEqual(status, 200, result)
        return result["case"]

    def body(self, case, **changes):
        result = {
            "reference": case["request"]["publicReference"], "email": case["request"]["email"],
            "version": case["version"], "checks": {
                "paymentEvidenceReviewed": True, "refundRulesReviewed": True,
                "supportingDetailsReviewed": True,
            }, "paymentReference": "LOCAL-EVIDENCE-01", "specialistRequired": False,
            "note": "Reviewed the local prototype evidence; no airline approval or payment.",
            "action": "save_review",
        }
        result.update(changes)
        return result

    def mutate(self, body, expected=200):
        status, _, result = self.call("/api/review-cases", body)
        self.assertEqual(status, expected, result)
        return result.get("case") if expected == 200 else result

    def test_old_schema_and_original_idempotency_survive_case_migration(self):
        case = self.get_case()
        self.assertEqual(case["request"]["publicReference"], REFERENCE)
        self.assertEqual(case["request"]["createdAt"], "2026-10-07T00:00:00Z")
        self.assertEqual(case["booking"]["source"]["mode"], "synthetic")
        self.assertEqual(case["reviewState"], "not_started")
        self.assertIsInstance(case["version"], int)
        status, _, result = self.call("/api/refund-requests", self.legacy_payload)
        self.assertEqual(status, 200, result)
        self.assertFalse(result["created"])
        self.assertEqual(result["request"]["publicReference"], REFERENCE)
        saved = self.mutate(self.body(case))
        status, _, result = self.call("/api/refund-requests", self.legacy_payload)
        self.assertEqual(status, 200, result)
        self.assertEqual(result["request"]["details"], self.legacy_payload["details"])
        self.assertEqual(result["request"]["review"]["version"], saved["version"])

    def test_case_owner_pair_required_and_no_unrestricted_list(self):
        case = self.get_case()
        for reference, email in ((REFERENCE, "wrong@example.com"), ("AF-NOTEXIST", EMAIL)):
            status, _, result = self.call("/api/review-cases?" + urlencode({"reference": reference, "email": email}))
            self.assertEqual(status, 404, result)
            self.assertEqual(result["error"]["code"], "REQUEST_NOT_FOUND")
            self.assertNotIn("case", result)
            rejected = self.mutate(self.body(case, reference=reference, email=email), expected=404)
            self.assertNotIn("case", rejected)
        status, _, result = self.call("/api/review-cases")
        self.assertEqual(status, 400, result)
        self.assertNotIn("case", result)
        self.assertEqual(self.get_case()["version"], case["version"])

    def test_missing_required_evidence_blocks_handoff_without_mutating(self):
        initial = self.get_case()
        partial = self.mutate(self.body(initial, checks={
            "paymentEvidenceReviewed": False, "refundRulesReviewed": False,
            "supportingDetailsReviewed": False,
        }, paymentReference=""))
        self.assertEqual(partial["version"], initial["version"] + 1)
        self.assertEqual(partial["reviewState"], "prepared")
        self.assertEqual(partial["request"]["status"], "information_needed")
        self.assertEqual(partial["triage"]["route"], "information_needed")
        self.assertEqual(partial["triage"]["queue"], "Information follow-up")
        self.assertEqual(partial["triage"]["ownerRole"], "Case coordinator")
        self.assertFalse(partial["triage"]["readyForHandoff"])
        self.assertTrue(partial["request"]["review"]["missingItems"])
        self.mutate(self.body(partial, action="handoff", checks=partial["checks"], paymentReference=""), expected=409)
        unchanged = self.get_case()
        self.assertEqual(unchanged["version"], partial["version"])
        self.assertEqual(unchanged["events"], partial["events"])

    def test_standard_handoff_reopen_and_receipt_share_persisted_state(self):
        initial = self.get_case()
        prepared = self.mutate(self.body(initial))
        self.assertEqual(prepared["triage"]["route"], "standard")
        self.assertEqual(prepared["triage"]["queue"], "Standard review")
        self.assertEqual(prepared["triage"]["ownerRole"], "Refund reviewer")
        self.assertEqual(prepared["triage"]["ruleVersion"], "prototype-v1")
        self.assertTrue(prepared["triage"]["readyForHandoff"])
        self.assertTrue(prepared["triage"]["reasons"])
        self.assertEqual(prepared["request"]["status"], "review_prepared")
        queued = self.mutate(self.body(prepared, action="handoff", note="Send the local case to standard review."))
        self.assertEqual(queued["reviewState"], "queued")
        self.assertEqual(queued["request"]["status"], "queued_for_review")
        self.assertEqual(queued["version"], prepared["version"] + 1)
        self.assertEqual(queued["events"][-1]["version"], queued["version"])
        self.assertEqual(queued["events"][-1]["queue"], "Standard review")
        self.assertEqual(queued["request"]["source"]["mode"], "local")
        self.assertIsNone(queued["request"]["sapCreditMemoRequestId"])
        self.assertEqual(self.sap.calls, 0)
        for action in ("save_review", "handoff"):
            self.mutate(self.body(queued, action=action), expected=409)
        self.stop_server()
        self.start_server()
        persisted = self.get_case()
        self.assertEqual(persisted, queued)
        status, _, result = self.call("/api/refund-requests?" + urlencode({"reference": REFERENCE, "email": EMAIL}))
        self.assertEqual(status, 200, result)
        self.assertEqual(result["request"], persisted["request"])
        status, headers, result = self.call("/api/refund-requests/receipt?" + urlencode({"reference": REFERENCE, "email": EMAIL}))
        self.assertEqual(status, 200, result)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertEqual(result["receipt"], persisted["request"])
        reopened = self.mutate(self.body(persisted, action="reopen", note="Reopen the local case to check newly supplied information."))
        self.assertEqual(reopened["reviewState"], "prepared")
        self.assertEqual(reopened["version"], persisted["version"] + 1)
        self.assertEqual(len(reopened["events"]), len(persisted["events"]) + 1)
        self.assertEqual(reopened["events"][-1]["note"], "Reopen the local case to check newly supplied information.")

    def test_other_reason_and_specialist_flag_route_to_complex(self):
        other = dict(self.legacy_payload, email="other@example.com", reason="other", details="", requestKey=str(uuid.uuid4()))
        status, _, result = self.call("/api/refund-requests", other)
        self.assertEqual(status, 201, result)
        other_case = self.get_case(result["request"]["publicReference"], other["email"])
        missing = self.mutate(self.body(other_case, checks={
            "paymentEvidenceReviewed": True, "refundRulesReviewed": True,
            "supportingDetailsReviewed": False,
        }))
        self.assertEqual(missing["triage"]["route"], "information_needed")
        complex_case = self.mutate(self.body(missing))
        self.assertEqual(complex_case["triage"]["route"], "complex")
        self.assertEqual(complex_case["triage"]["queue"], "Specialist review")
        self.assertEqual(complex_case["triage"]["ownerRole"], "Refund specialist")
        self.assertTrue(complex_case["triage"]["reasons"])
        flagged = self.mutate(self.body(self.get_case(), specialistRequired=True))
        self.assertEqual(flagged["triage"]["route"], "complex")
        self.assertTrue(flagged["specialistRequired"])
        self.assertEqual(self.sap.calls, 0)

    def test_same_version_concurrent_writers_one_wins_one_conflicts(self):
        initial = self.get_case()
        bodies = [self.body(initial, note=note) for note in ("Independent local review A.", "Independent local review B.")]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda body: self.call("/api/review-cases", body), bodies))
        self.assertEqual(sorted(status for status, _, _ in results), [200, 409])
        persisted = self.get_case()
        self.assertEqual(persisted["version"], initial["version"] + 1)
        self.assertEqual(len(persisted["events"]), len(initial["events"]) + 1)
        self.assertIn(persisted["reviewNote"], {body["note"] for body in bodies})
        self.assertEqual(persisted["events"][-1]["note"], persisted["reviewNote"])
        self.assertEqual(persisted["events"][-1]["version"], persisted["version"])

    def test_strict_review_inputs_and_invalid_transitions_preserve_version(self):
        initial = self.get_case()
        bad_inputs = (
            {"version": True}, {"version": -1}, {"version": "0"},
            {"checks": {"paymentEvidenceReviewed": 1, "refundRulesReviewed": True, "supportingDetailsReviewed": True}},
            {"checks": {"paymentEvidenceReviewed": True, "refundRulesReviewed": True}},
            {"checks": dict(self.body(initial)["checks"], unreviewedField=False)},
            {"paymentReference": ""}, {"paymentReference": "x" * 81},
            {"paymentReference": "REF\u0000ID"}, {"paymentReference": "REF\nID"}, {"paymentReference": "REF\tID"},
            {"specialistRequired": "false"}, {"note": ""}, {"note": "x" * 1001},
            {"action": "approve_refund"}, {"action": []}, {"action": {}},
        )
        for changes in bad_inputs:
            with self.subTest(changes=changes):
                self.mutate(self.body(initial, **changes), expected=400)
        self.mutate(self.body(initial, action="reopen"), expected=409)
        self.assertEqual(self.get_case()["version"], initial["version"])
        self.assertEqual(self.get_case()["events"], initial["events"])
        self.assertEqual(self.sap.calls, 0)


if __name__ == "__main__":
    unittest.main()
