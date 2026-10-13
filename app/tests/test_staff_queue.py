"""Behavior checks for the staff case queue endpoint."""
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
# Test-only code, generated here rather than read from the server, so the suite never touches app/.env.
STAFF_CODE = "test-staff-code-" + uuid.uuid4().hex[:8]
LIVE_RECORD = {
    "id": "10000001", "totalNetAmount": 248.0, "currency": "NZD",
    "source": {"mode": "live", "label": "SAP credit memo request", "fetchedAt": "2026-10-14T00:00:00Z"},
}


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


class StaffQueueHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="runtime-", dir=TEST_TEMP_DIR)
        folder = Path(self.temp.name)
        public = folder / "public"
        public.mkdir()
        (public / "index.html").write_text("test-public-page", encoding="utf-8")
        self.store = server.ApplicationStore(folder / "data.sqlite3")
        self.httpd = server.make_server(self.store, server.SAPClient(server.SAPConfig()), public_dir=public,
                                        port=0, staff_access_code=STAFF_CODE)
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
            return response.status, response.read()

    def submit(self, email):
        status, raw = self.call("/api/refund-requests", payload(email=email))
        self.assertEqual(status, 201)
        return json.loads(raw)["request"]

    def queue(self, state=None, code=STAFF_CODE):
        suffix = "" if state is None else "?" + urlencode({"state": state})
        return self.call("/api/staff/queue" + suffix, headers={"X-Staff-Code": code})

    def cases(self, state=None, code=STAFF_CODE):
        status, raw = self.queue(state, code)
        self.assertEqual(status, 200)
        return json.loads(raw)["cases"]

    def assertUnauthorized(self, status, raw):
        self.assertEqual(status, 401)
        body = json.loads(raw)
        self.assertEqual(body["error"]["code"], "STAFF_UNAUTHORIZED")
        self.assertTrue(body["error"]["message"])

    def test_missing_code_is_rejected(self):
        self.submit("alex@example.com")
        self.assertUnauthorized(*self.call("/api/staff/queue"))

    def test_wrong_code_is_rejected(self):
        self.submit("alex@example.com")
        self.assertUnauthorized(*self.queue(code="not-the-code"))

    def test_non_ascii_code_is_rejected_without_a_server_error(self):
        # secrets.compare_digest raises TypeError for str input holding non-ASCII characters,
        # so a bad header must still be a clean 401 rather than a 500.
        self.submit("alex@example.com")
        self.assertUnauthorized(*self.queue(code="caf\u00e9-code"))

    def test_queue_returns_submitted_cases_newest_first_with_required_fields(self):
        oldest = self.submit("first@example.com")
        middle = self.submit("second@example.com")
        newest = self.submit("third@example.com")
        cases = self.cases()
        self.assertEqual([case["publicReference"] for case in cases],
                         [newest["publicReference"], middle["publicReference"], oldest["publicReference"]])
        first = cases[0]
        self.assertEqual(
            set(first),
            {"publicReference", "email", "reason", "reviewState", "version", "createdAt", "updatedAt", "triage"},
        )
        self.assertEqual(set(first["triage"]), {"route", "routeLabel", "queue"})
        self.assertEqual(first["email"], "third@example.com")
        self.assertEqual(first["reason"], "flight_cancelled")
        self.assertEqual(first["reviewState"], "not_started")
        self.assertEqual(first["version"], 0)
        self.assertEqual((first["createdAt"], first["updatedAt"]), (newest["createdAt"], newest["createdAt"]))
        self.assertEqual(first["triage"]["route"], "information_needed")
        self.assertEqual(first["triage"]["routeLabel"], "Information needed")
        self.assertEqual(first["triage"]["queue"], "Information follow-up")

    def test_state_filter_selects_matching_cases(self):
        queued = self.submit("queued@example.com")
        self.submit("waiting@example.com")
        status, raw = self.call("/api/review-cases", review_body(queued, action="handoff"))
        self.assertEqual(status, 200)

        self.assertEqual([case["publicReference"] for case in self.cases("queued")], [queued["publicReference"]])
        not_started = self.cases("not_started")
        self.assertEqual([case["email"] for case in not_started], ["waiting@example.com"])
        self.assertEqual(self.cases("prepared"), [])
        self.assertEqual(len(self.cases()), 2)
        self.assertEqual(self.cases("queued")[0]["reviewState"], "queued")
        self.assertEqual(self.cases("queued")[0]["version"], 1)
        self.assertEqual(self.cases("queued")[0]["triage"]["queue"], "Standard review")

    def test_invalid_state_is_rejected(self):
        self.submit("alex@example.com")
        status, raw = self.queue(state="archived")
        self.assertEqual(status, 400)
        body = json.loads(raw)
        self.assertEqual(body["error"]["code"], "INVALID_INPUT")
        self.assertTrue(body["error"]["message"])

    def test_captured_not_started_row_matches_the_not_started_filter(self):
        # capture_financial_reference persists an explicit 'not_started' review row, so the filter
        # must match that row as well as a case that has no review row at all.
        record = self.submit("captured@example.com")
        self.store.capture_financial_reference(
            server.validate_financial_reference_payload({
                "reference": record["publicReference"], "email": record["email"], "version": 0,
                "documentId": LIVE_RECORD["id"], "note": "Demonstration reference.",
            }),
            LIVE_RECORD,
        )
        not_started = self.cases("not_started")
        self.assertEqual([case["publicReference"] for case in not_started], [record["publicReference"]])
        self.assertEqual(not_started[0]["reviewState"], "not_started")
        self.assertEqual(not_started[0]["version"], 1)
        self.assertEqual(self.cases("prepared"), [])
        self.assertEqual(self.cases("queued"), [])

    def test_queue_is_limited_to_the_hundred_newest_cases(self):
        with self.store.connect() as connection:
            for index in range(105):
                connection.execute(
                    "INSERT INTO refund_requests VALUES (?, 'NZ7K2H', 'Taylor', ?, 'flight_cancelled', '', ?, 248.0, 'NZD')",
                    ("AF-%012X" % index, f"bulk{index}@example.com", f"2026-10-14T10:{index // 60:02d}:{index % 60:02d}Z"),
                )
        cases = self.cases()
        self.assertEqual(len(cases), 100)
        self.assertEqual(cases[0]["email"], "bulk104@example.com")
        self.assertEqual(cases[-1]["email"], "bulk5@example.com")

    def test_server_without_a_staff_code_refuses_the_queue(self):
        other = server.make_server(self.store, server.SAPClient(server.SAPConfig()),
                                   public_dir=Path(self.temp.name) / "public", port=0, staff_access_code="")
        thread = threading.Thread(target=other.serve_forever, daemon=True)
        thread.start()
        try:
            request = Request(f"http://127.0.0.1:{other.server_port}/api/staff/queue", headers={"X-Staff-Code": ""})
            try:
                response = urlopen(request, timeout=5)
            except HTTPError as error:
                response = error
            with response:
                self.assertEqual(response.status, 401)
        finally:
            other.shutdown()
            other.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
