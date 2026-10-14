"""Staff endpoints: the request queue, routing rules and approve/decline decisions."""
import tempfile
import unittest
import uuid
from pathlib import Path

from refund_support import (PASSENGER, PASSENGER_PASSWORD, STAFF, STAFF_PASSWORD,
                            APIServer, FakeSAP, make_auth, public_dir, server)


def submission(email="mark.don@example.com", request_key=None):
    return {"email": email, "confirmed": True, "requestKey": request_key or str(uuid.uuid4())}


class StaffAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="runtime-", dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.sap = FakeSAP()
        self.store = server.ApplicationStore(self.folder / "data.sqlite3")
        self.api = APIServer(self.store, self.sap, public_dir(self.folder), make_auth())
        self.addCleanup(self.api.close)
        self.staff_token = self.api.login(STAFF, STAFF_PASSWORD)["token"]
        self.passenger_token = self.api.login(PASSENGER, PASSENGER_PASSWORD)["token"]

    def auth(self, token):
        return {"Authorization": "Bearer " + token}

    def submit(self, email="mark.don@example.com"):
        status, _, body = self.api.json_call("/api/refund-requests", submission(email),
                                             headers=self.auth(self.passenger_token))
        self.assertEqual(status, 201)
        return body["request"]

    def test_seeded_demo_request_is_visible_to_staff(self):
        status, _, body = self.api.json_call("/api/staff/requests", headers=self.auth(self.staff_token))
        self.assertEqual(status, 200)
        seeded = [record for record in body["requests"] if record["reference"] == "AF-DEMO000001"]
        self.assertEqual(len(seeded), 1)
        record = seeded[0]
        self.assertEqual((record["passengerName"], record["bookingReference"]), ("Minh Nguyen", "NZ9P4K"))
        self.assertEqual((record["sapDocument"], record["amount"], record["currency"]), ("60000049", 400.0, "USD"))
        self.assertEqual(record["sapStatus"], "A")
        self.assertEqual(record["route"], "specialist")
        self.assertEqual(record["status"], "pending")
        self.assertEqual(record["quoteSource"], "SAP snapshot captured 2026-10-14")

    def test_queue_is_newest_first_and_contains_every_field_staff_need(self):
        created = self.submit()
        _, _, body = self.api.json_call("/api/staff/requests", headers=self.auth(self.staff_token))
        references = [record["reference"] for record in body["requests"]]
        self.assertIn(created["reference"], references)
        self.assertIn("AF-DEMO000001", references)
        timestamps = [record["createdAt"] for record in body["requests"]]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))
        record = next(item for item in body["requests"] if item["reference"] == created["reference"])
        for field in ("reference", "bookingReference", "passengerName", "email", "reason", "refundType",
                      "sapDocument", "sapStatus", "amount", "currency", "quoteFetchedAt", "quoteSource",
                      "route", "status", "version", "createdAt", "events"):
            self.assertIn(field, record)

    def test_only_staff_may_read_or_decide(self):
        self.assertEqual(self.api.call("/api/staff/requests")[0], 401)
        self.assertEqual(self.api.call("/api/staff/requests", headers=self.auth(self.passenger_token))[0], 403)
        created = self.submit()
        path = "/api/staff/requests/" + created["reference"] + "/decision"
        body = {"decision": "approve", "note": "", "version": 1}
        self.assertEqual(self.api.json_call(path, body)[0], 401)
        self.assertEqual(self.api.json_call(path, body, headers=self.auth(self.passenger_token))[0], 403)

    def test_approval_records_status_version_note_and_event(self):
        created = self.submit()
        path = "/api/staff/requests/" + created["reference"] + "/decision"
        status, _, body = self.api.json_call(path, {"decision": "approve", "note": "Refund approved for payout.",
                                                    "version": 1}, headers=self.auth(self.staff_token))
        self.assertEqual(status, 200)
        record = body["request"]
        self.assertEqual((record["status"], record["version"]), ("approved", 2))
        self.assertEqual(record["decisionNote"], "Refund approved for payout.")
        event = record["events"][-1]
        self.assertEqual(event["type"], "approved")
        self.assertEqual(event["staff"], "Refunds team")
        self.assertEqual(event["note"], "Refund approved for payout.")
        self.assertTrue(event["at"])

    def test_decline_requires_a_note_and_keeps_the_note(self):
        created = self.submit()
        path = "/api/staff/requests/" + created["reference"] + "/decision"
        self.assertEqual(self.api.json_call(path, {"decision": "decline", "note": "  ", "version": 1},
                                            headers=self.auth(self.staff_token))[0], 400)
        self.assertEqual(self.api.json_call(path, {"decision": "decline", "note": "x" * 501, "version": 1},
                                            headers=self.auth(self.staff_token))[0], 400)
        status, _, body = self.api.json_call(path, {"decision": "decline", "note": "Duplicate booking found.",
                                                    "version": 1}, headers=self.auth(self.staff_token))
        self.assertEqual(status, 200)
        self.assertEqual((body["request"]["status"], body["request"]["decisionNote"]),
                         ("declined", "Duplicate booking found."))

    def test_already_decided_and_stale_versions_are_conflicts(self):
        created = self.submit()
        path = "/api/staff/requests/" + created["reference"] + "/decision"
        self.api.json_call(path, {"decision": "approve", "note": "", "version": 1},
                           headers=self.auth(self.staff_token))
        status, _, body = self.api.json_call(path, {"decision": "approve", "note": "", "version": 1},
                                             headers=self.auth(self.staff_token))
        self.assertEqual(status, 409)
        self.assertEqual(body["error"]["code"], "VERSION_CONFLICT")
        status, _, body = self.api.json_call(path, {"decision": "decline", "note": "Changed my mind.", "version": 2},
                                             headers=self.auth(self.staff_token))
        self.assertEqual(status, 409)
        self.assertEqual(body["error"]["code"], "REQUEST_ALREADY_DECIDED")

    def test_unknown_reference_and_invalid_decisions_are_rejected(self):
        path = "/api/staff/requests/AF-000000000000/decision"
        status, _, body = self.api.json_call(path, {"decision": "approve", "note": "", "version": 1},
                                             headers=self.auth(self.staff_token))
        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["code"], "REQUEST_NOT_FOUND")
        created = self.submit()
        live = "/api/staff/requests/" + created["reference"] + "/decision"
        for payload in ({"decision": "maybe", "note": "", "version": 1},
                        {"decision": "approve", "note": "", "version": 0},
                        {"decision": "approve", "note": "", "version": "1"},
                        {"decision": "approve", "note": 5, "version": 1}):
            self.assertEqual(self.api.json_call(live, payload, headers=self.auth(self.staff_token))[0], 400, payload)

    def test_routing_rule(self):
        direct_cancelled = {"channel": "direct", "flightStatus": "cancelled"}
        self.assertEqual(server.decide_route(direct_cancelled, "A", 300.0), "fast_track")
        self.assertEqual(server.decide_route(direct_cancelled, "A", 250.0), "fast_track")
        self.assertEqual(server.decide_route(direct_cancelled, "A", 300.01), "specialist")
        self.assertEqual(server.decide_route(direct_cancelled, "B", 250.0), "specialist")
        self.assertEqual(server.decide_route(direct_cancelled, "A", None), "specialist")
        self.assertEqual(server.decide_route({"channel": "agent", "flightStatus": "cancelled"}, "A", 250.0), "specialist")

    def test_over_three_hundred_is_routed_to_a_specialist(self):
        self.sap.record = dict(self.sap.record, totalNetAmount=400.0)
        created = self.submit()
        self.assertEqual(created["route"], "specialist")
        self.assertEqual(created["amount"], 400.0)


if __name__ == "__main__":
    unittest.main()
