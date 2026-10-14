"""Passenger endpoints: live SAP quote, one-step full refund submission and receipts."""
import json
import tempfile
import unittest
import uuid
from pathlib import Path

from refund_support import (PASSENGER, PASSENGER_PASSWORD, STAFF, STAFF_PASSWORD,
                            APIServer, FakeSAP, make_auth, public_dir, server)


def submission(email="mark.don@example.com", request_key=None, confirmed=True, booking="NZ7K2H"):
    return {"email": email, "confirmed": confirmed, "requestKey": request_key or str(uuid.uuid4()),
            "bookingReference": booking}


class PassengerAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="runtime-", dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.sap = FakeSAP()
        self.store = server.ApplicationStore(self.folder / "data.sqlite3")
        self.api = APIServer(self.store, self.sap, public_dir(self.folder), make_auth())
        self.addCleanup(self.api.close)
        self.token = self.api.login(PASSENGER, PASSENGER_PASSWORD)["token"]

    def auth(self, token=None):
        return {"Authorization": "Bearer " + (self.token if token is None else token)}

    def test_me_returns_live_sap_quote_and_no_request_initially(self):
        status, _, body = self.api.json_call("/api/me", headers=self.auth())
        self.assertEqual(status, 200)
        self.assertEqual(body["displayName"], "Mark Don")
        self.assertEqual([trip["booking"]["reference"] for trip in body["trips"]],
                         ["NZ2W6B", "NZ7K2H", "NZ5R8M", "NZ3Q1T"])
        live = next(trip for trip in body["trips"] if trip["booking"]["reference"] == "NZ7K2H")
        self.assertEqual(live["flight"]["flight"], "NZ6")
        self.assertEqual(live["flight"]["flightStatus"], "cancelled")
        self.assertEqual(live["booking"]["sapCreditMemoRequest"], "60000073")
        self.assertTrue(live["refundable"])
        self.assertEqual(live["quote"], {"sapDocument": "60000073", "amount": 250.0, "currency": "NZD",
                                         "processStatus": "A", "fetchedAt": "2026-10-14T00:00:00Z"})
        self.assertIsNone(live["quoteError"])
        self.assertIsNone(live["request"])
        self.assertEqual(self.sap.calls, ["60000073"])

    def test_me_reports_a_clear_quote_error_instead_of_a_fallback(self):
        self.sap.error = server.APIError(503, "SAP_UNCONFIGURED", "Configure the personal SAP API key.")
        status, _, body = self.api.json_call("/api/me", headers=self.auth())
        self.assertEqual(status, 200)
        live = next(trip for trip in body["trips"] if trip["booking"]["reference"] == "NZ7K2H")
        self.assertIsNone(live["quote"])
        self.assertEqual(live["quoteError"]["code"], "SAP_UNCONFIGURED")
        self.assertIsNone(live["request"])

    def test_sign_in_is_required_for_passenger_endpoints(self):
        for path in ("/api/me", "/api/refund-requests/receipt?booking=NZ7K2H"):
            self.assertEqual(self.api.call(path)[0], 401, path)
        self.assertEqual(self.api.json_call("/api/refund-requests", submission())[0], 401)

    def test_submit_creates_a_pending_full_refund_request_with_the_quote_snapshot(self):
        status, _, body = self.api.json_call("/api/refund-requests", submission(), headers=self.auth())
        self.assertEqual(status, 201)
        self.assertTrue(body["created"])
        record = body["request"]
        self.assertTrue(record["reference"].startswith("AF-"))
        self.assertEqual((record["bookingReference"], record["passengerName"]), ("NZ7K2H", "Mark Don"))
        self.assertEqual((record["reason"], record["refundType"]), ("flight_disruption", "full"))
        self.assertEqual((record["amount"], record["currency"], record["sapDocument"]), (250.0, "NZD", "60000073"))
        self.assertEqual((record["sapStatus"], record["quoteSource"]), ("A", "live"))
        self.assertEqual((record["status"], record["version"], record["route"]), ("pending", 1, "fast_track"))
        self.assertEqual([event["type"] for event in record["events"]], ["submitted"])
        self.assertIsNotNone(self.store.request_for_booking("NZ7K2H"))

    def test_submission_is_blocked_without_a_live_quote(self):
        self.sap.error = server.APIError(503, "SAP_UNAVAILABLE", "SAP is temporarily unavailable.")
        status, _, body = self.api.json_call("/api/refund-requests", submission(), headers=self.auth())
        self.assertEqual(status, 503)
        self.assertEqual(body["error"]["code"], "SAP_UNAVAILABLE")
        self.assertIsNone(self.store.request_for_booking("NZ7K2H"))

    def test_submission_is_blocked_when_sap_has_no_amount(self):
        record = dict(self.sap.record)
        record["totalNetAmount"] = None
        self.sap.record = record
        status, _, body = self.api.json_call("/api/refund-requests", submission(), headers=self.auth())
        self.assertEqual(status, 502)
        self.assertEqual(body["error"]["code"], "SAP_QUOTE_INCOMPLETE")
        self.assertIsNone(self.store.request_for_booking("NZ7K2H"))

    def test_repeating_the_same_request_key_returns_the_same_request(self):
        body = submission()
        _, _, first = self.api.json_call("/api/refund-requests", body, headers=self.auth())
        self.sap.calls.clear()
        status, _, second = self.api.json_call("/api/refund-requests", body, headers=self.auth())
        self.assertEqual(status, 200)
        self.assertFalse(second["created"])
        self.assertEqual(second["request"], first["request"])
        # A repeat never reads SAP again and never creates a second record.
        self.assertEqual(self.sap.calls, [])
        self.assertEqual(len(self.store.staff_requests()), 4)

    def test_same_request_key_with_a_different_payload_is_a_conflict(self):
        body = submission()
        self.api.json_call("/api/refund-requests", body, headers=self.auth())
        changed = dict(body, email="someone.else@example.com")
        status, _, response = self.api.json_call("/api/refund-requests", changed, headers=self.auth())
        self.assertEqual(status, 409)
        self.assertEqual(response["error"]["code"], "IDEMPOTENCY_CONFLICT")

    def test_one_request_per_booking_returns_the_original(self):
        _, _, first = self.api.json_call("/api/refund-requests", submission(), headers=self.auth())
        status, _, second = self.api.json_call("/api/refund-requests", submission(), headers=self.auth())
        self.assertEqual(status, 200)
        self.assertFalse(second["created"])
        self.assertEqual(second["request"]["reference"], first["request"]["reference"])
        self.assertEqual(len(self.store.staff_requests()), 4)

    def test_confirmation_and_email_are_validated(self):
        self.assertEqual(self.api.json_call("/api/refund-requests", submission(confirmed=False),
                                            headers=self.auth())[0], 400)
        self.assertEqual(self.api.json_call("/api/refund-requests", submission(email="not-an-email"),
                                            headers=self.auth())[0], 400)
        self.assertEqual(self.api.json_call("/api/refund-requests", submission(request_key="not-a-uuid"),
                                            headers=self.auth())[0], 400)
        self.assertEqual(self.api.json_call("/api/refund-requests", {"email": "a@b.example"},
                                            headers=self.auth())[0], 400)

    def test_staff_cannot_use_passenger_endpoints(self):
        staff_token = self.api.login(STAFF, STAFF_PASSWORD)["token"]
        self.assertEqual(self.api.json_call("/api/me", headers=self.auth(staff_token))[0], 403)
        self.assertEqual(self.api.json_call("/api/refund-requests", submission(),
                                            headers=self.auth(staff_token))[0], 403)

    def test_receipt_downloads_the_owners_json(self):
        self.assertEqual(self.api.call("/api/refund-requests/receipt?booking=NZ7K2H", headers=self.auth())[0], 404)
        _, _, created = self.api.json_call("/api/refund-requests", submission(), headers=self.auth())
        status, headers, raw = self.api.call("/api/refund-requests/receipt?booking=NZ7K2H", headers=self.auth())
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertEqual(json.loads(raw)["receipt"]["reference"], created["request"]["reference"])

    def test_oversized_and_non_json_bodies_are_rejected(self):
        status, _, _ = self.api.raw("/api/refund-requests", b"x" * (server.MAX_BODY_BYTES + 1),
                                    headers=self.auth())
        self.assertEqual(status, 413)
        self.assertEqual(self.api.raw("/api/refund-requests", b"not json", headers=self.auth())[0], 400)
        self.assertEqual(self.api.raw("/api/refund-requests", b"{}", content_type="text/plain",
                                      headers=self.auth())[0], 415)
        self.assertEqual(self.api.raw("/api/refund-requests", b"", headers=self.auth())[0], 413)

    def test_errors_never_leak_credentials_tokens_or_email_addresses(self):
        secret_email = "private.passenger@example.com"
        bodies = []
        bodies.append(self.api.json_call("/api/auth/login",
                                         {"username": PASSENGER, "password": PASSENGER_PASSWORD + "-x"})[2])
        self.sap.error = server.APIError(503, "SAP_UNAVAILABLE", "SAP is temporarily unavailable.")
        bodies.append(self.api.json_call("/api/refund-requests", submission(email=secret_email),
                                         headers=self.auth())[2])
        self.sap.error = None
        bodies.append(self.api.json_call("/api/refund-requests", submission(email="nope"),
                                         headers=self.auth())[2])
        staff_token = self.api.login(STAFF, STAFF_PASSWORD)["token"]
        bodies.append(self.api.json_call("/api/me", headers=self.auth(staff_token))[2])
        rendered = json.dumps(bodies)
        for secret in (PASSENGER_PASSWORD, STAFF_PASSWORD, self.token, secret_email):
            self.assertNotIn(secret, rendered)


class MultipleTripsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="runtime-", dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.sap = FakeSAP()
        self.store = server.ApplicationStore(self.folder / "data.sqlite3")
        self.api = APIServer(self.store, self.sap, public_dir(self.folder), make_auth())
        self.addCleanup(self.api.close)
        self.token = self.api.login(PASSENGER, PASSENGER_PASSWORD)["token"]

    def auth(self, token=None):
        return {"Authorization": "Bearer " + (self.token if token is None else token)}

    def test_trips_are_ordered_by_flight_date_with_refundable_flags(self):
        _, _, body = self.api.json_call("/api/me", headers=self.auth())
        trips = {trip["booking"]["reference"]: trip for trip in body["trips"]}
        self.assertEqual([trip["booking"]["reference"] for trip in body["trips"]],
                         ["NZ2W6B", "NZ7K2H", "NZ5R8M", "NZ3Q1T"])
        self.assertEqual(
            {reference: trip["refundable"] for reference, trip in trips.items()},
            {"NZ2W6B": True, "NZ7K2H": True, "NZ5R8M": True, "NZ3Q1T": False})
        # Only the refundable trip without a request carries a live quote.
        live = trips["NZ7K2H"]
        self.assertIn("quote", live)
        self.assertNotIn("quote", trips["NZ3Q1T"])
        self.assertNotIn("quote", trips["NZ5R8M"])
        self.assertNotIn("quote", trips["NZ2W6B"])

    def test_seeded_pending_and_approved_requests_are_attached_to_trips(self):
        _, _, body = self.api.json_call("/api/me", headers=self.auth())
        trips = {trip["booking"]["reference"]: trip for trip in body["trips"]}
        pending = trips["NZ5R8M"]["request"]
        self.assertEqual((pending["reference"], pending["status"], pending["route"]),
                         ("AF-DEMO000002", "pending", "specialist"))
        self.assertEqual((pending["sapDocument"], pending["amount"], pending["currency"]),
                         ("60000062", 175.50, "USD"))
        approved = trips["NZ2W6B"]["request"]
        self.assertEqual((approved["reference"], approved["status"], approved["route"]),
                         ("AF-DEMO000003", "approved", "specialist"))
        self.assertEqual((approved["sapDocument"], approved["amount"]), ("60000026", 60.00))
        self.assertIsNone(trips["NZ7K2H"]["request"])
        self.assertIsNone(trips["NZ3Q1T"]["request"])

    def test_submission_requires_ownership_and_refundability(self):
        status, _, body = self.api.json_call(
            "/api/refund-requests", submission(booking="NZ9P4K"), headers=self.auth())
        self.assertEqual(status, 404)
        status, _, _ = self.api.json_call(
            "/api/refund-requests", submission(booking="NZ0000"), headers=self.auth())
        self.assertEqual(status, 404)
        status, _, body = self.api.json_call(
            "/api/refund-requests", submission(booking="NZ3Q1T"), headers=self.auth())
        self.assertEqual(status, 400)
        status, _, body = self.api.json_call(
            "/api/refund-requests", {"email": "a@b.example", "confirmed": True,
                                     "requestKey": str(uuid.uuid4())}, headers=self.auth())
        self.assertEqual(status, 400)

    def test_per_booking_submission_and_receipt_by_booking(self):
        status, _, created = self.api.json_call(
            "/api/refund-requests", submission(), headers=self.auth())
        self.assertEqual(status, 201)
        self.assertEqual(created["request"]["bookingReference"], "NZ7K2H")
        # Seeded bookings already have one request each.
        for reference in ("NZ5R8M", "NZ2W6B"):
            status, _, body = self.api.json_call(
                "/api/refund-requests", submission(booking=reference), headers=self.auth())
            self.assertEqual(status, 200)
            self.assertFalse(body["created"])
        status, headers, raw = self.api.call(
            "/api/refund-requests/receipt?booking=NZ5R8M", headers=self.auth())
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["receipt"]["reference"], "AF-DEMO000002")
        status, _, raw = self.api.call(
            "/api/refund-requests/receipt?booking=NZ2W6B", headers=self.auth())
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["receipt"]["reference"], "AF-DEMO000003")
        self.assertEqual(self.api.call("/api/refund-requests/receipt", headers=self.auth())[0], 400)
        self.assertEqual(self.api.call(
            "/api/refund-requests/receipt?booking=NZ9P4K", headers=self.auth())[0], 404)


if __name__ == "__main__":
    unittest.main()
