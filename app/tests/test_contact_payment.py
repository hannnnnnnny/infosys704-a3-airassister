"""Task 5c: contact details and synthetic original payment methods."""
import json
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

from refund_support import (PASSENGER, PASSENGER_PASSWORD, STAFF, STAFF_PASSWORD,
                            APIServer, FakeSAP, make_auth, public_dir, server)


def contact_submission(*, phone="", email="", request_key=None, booking="NZ7K2H",
                       extra=None, legacy_email=None):
    payload = {"confirmed": True, "requestKey": request_key or str(uuid.uuid4()),
               "bookingReference": booking}
    if legacy_email is not None:
        payload["email"] = legacy_email
    else:
        payload["contact"] = {"phone": phone, "email": email}
    if extra:
        payload.update(extra)
    return payload


class ContactPaymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="runtime-", dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.sap = FakeSAP()
        self.store = server.ApplicationStore(self.folder / "data.sqlite3")
        self.api = APIServer(self.store, self.sap, public_dir(self.folder), make_auth())
        self.addCleanup(self.api.close)
        self.passenger_token = self.api.login(PASSENGER, PASSENGER_PASSWORD)["token"]
        self.staff_token = self.api.login(STAFF, STAFF_PASSWORD)["token"]

    def auth(self, token):
        return {"Authorization": "Bearer " + token}

    def test_at_least_one_contact_is_required(self):
        for payload in (
            contact_submission(phone="", email=""),
            {"confirmed": True, "requestKey": str(uuid.uuid4()), "bookingReference": "NZ7K2H"},
            contact_submission(phone="   ", email="   "),
        ):
            status, _, body = self.api.json_call("/api/refund-requests", payload,
                                                 headers=self.auth(self.passenger_token))
            self.assertEqual(status, 400, payload)

    def test_invalid_phone_and_email_are_rejected(self):
        bad_phones = ["abc", "123456", "x" * 21, "123-ABC-4567", "12+34!"]
        for phone in bad_phones:
            status, _, _ = self.api.json_call(
                "/api/refund-requests", contact_submission(phone=phone, email=""),
                headers=self.auth(self.passenger_token))
            self.assertEqual(status, 400, phone)
        for email in ("not-an-email", "a@b", "a@b@c.d e"):
            status, _, _ = self.api.json_call(
                "/api/refund-requests", contact_submission(phone="", email=email),
                headers=self.auth(self.passenger_token))
            self.assertEqual(status, 400, email)

    def test_phone_only_submission_stores_empty_email(self):
        status, _, body = self.api.json_call(
            "/api/refund-requests", contact_submission(phone="+64 21 555 0100", email=""),
            headers=self.auth(self.passenger_token))
        self.assertEqual(status, 201)
        record = body["request"]
        self.assertEqual(record["email"], "")
        self.assertEqual(record["phone"], "+64 21 555 0100")
        self.assertEqual(record["contact"], {"phone": "+64 21 555 0100", "email": ""})

    def test_payment_method_returned_but_cannot_be_overridden(self):
        payload = contact_submission(phone="+64 21 555 0100", email="mark.don@example.com",
                                     extra={"paymentMethod": {"type": "card", "brand": "Evil", "last4": "9999"},
                                            "destination": "bank-transfer"})
        status, _, body = self.api.json_call("/api/refund-requests", payload,
                                             headers=self.auth(self.passenger_token))
        self.assertEqual(status, 201)
        self.assertEqual(body["request"]["paymentMethod"],
                         {"type": "card", "brand": "Visa", "last4": "4242"})

    def test_payment_method_in_me_trips(self):
        status, _, body = self.api.json_call("/api/me", headers=self.auth(self.passenger_token))
        self.assertEqual(status, 200)
        trips = {trip["booking"]["reference"]: trip for trip in body["trips"]}
        self.assertEqual(trips["NZ7K2H"]["paymentMethod"],
                         {"type": "card", "brand": "Visa", "last4": "4242"})
        self.assertEqual(trips["NZ7K2H"]["booking"]["paymentMethod"],
                         {"type": "card", "brand": "Visa", "last4": "4242"})
        # Each booking has a distinct synthetic method; only check the owned ones here.
        self.assertEqual(trips["NZ5R8M"]["paymentMethod"]["brand"], "Amex")
        self.assertEqual(trips["NZ2W6B"]["paymentMethod"]["brand"], "Mastercard")
        self.assertEqual(server.PAYMENT_METHODS["NZ9P4K"]["brand"], "Mastercard")

    def test_contact_visible_to_staff(self):
        self.api.json_call("/api/refund-requests",
                           contact_submission(phone="+64 21 555 0100", email="mark.don@example.com"),
                           headers=self.auth(self.passenger_token))
        _, _, body = self.api.json_call("/api/staff/requests", headers=self.auth(self.staff_token))
        created = next(r for r in body["requests"] if r["bookingReference"] == "NZ7K2H")
        self.assertEqual(created["contact"], {"phone": "+64 21 555 0100", "email": "mark.don@example.com"})
        self.assertEqual(created["paymentMethod"], {"type": "card", "brand": "Visa", "last4": "4242"})
        # Decision responses keep contact + payment so staff can follow up after a decline.
        path = "/api/staff/requests/" + created["reference"] + "/decision"
        _, _, decided = self.api.json_call(path, {"decision": "decline", "note": "Fare rules apply.",
                                                  "version": 1}, headers=self.auth(self.staff_token))
        self.assertEqual(decided["request"]["contact"],
                         {"phone": "+64 21 555 0100", "email": "mark.don@example.com"})
        self.assertEqual(decided["request"]["paymentMethod"],
                         {"type": "card", "brand": "Visa", "last4": "4242"})

    def test_seeded_requests_have_contact_and_demo_reset_restores_them(self):
        _, _, body = self.api.json_call("/api/staff/requests", headers=self.auth(self.staff_token))
        seeded = next(r for r in body["requests"] if r["reference"] == "AF-DEMO000001")
        self.assertEqual(seeded["contact"],
                         {"phone": server.SEED_PHONE, "email": server.SEED_EMAIL})
        _, _, reset = self.api.json_call("/api/staff/demo-reset", body={},
                                         headers=self.auth(self.staff_token))
        seeded = next(r for r in reset["requests"] if r["reference"] == "AF-DEMO000001")
        self.assertEqual(seeded["contact"],
                         {"phone": server.SEED_PHONE, "email": server.SEED_EMAIL})

    def test_errors_never_leak_phone_numbers(self):
        secret_phone = "+64 21 555 0999"
        status, _, body = self.api.json_call(
            "/api/refund-requests", contact_submission(phone=secret_phone, email="not-an-email"),
            headers=self.auth(self.passenger_token))
        self.assertEqual(status, 400)
        self.assertNotIn(secret_phone, json.dumps(body))

    def test_older_rows_without_phone_still_load(self):
        legacy = self.folder / "legacy-nophone.sqlite3"
        connection = sqlite3.connect(legacy)
        connection.executescript("""
            CREATE TABLE refund_requests (
                public_reference TEXT PRIMARY KEY, booking_reference TEXT NOT NULL, last_name TEXT NOT NULL,
                email TEXT NOT NULL, reason TEXT NOT NULL, details TEXT NOT NULL, created_at TEXT NOT NULL,
                ticket_value REAL NOT NULL, currency TEXT NOT NULL, UNIQUE(booking_reference, email));
            CREATE TABLE submission_keys (
                request_key TEXT PRIMARY KEY, payload_hash TEXT NOT NULL,
                public_reference TEXT NOT NULL REFERENCES refund_requests(public_reference));
            INSERT INTO refund_requests VALUES
                ('AF-LEGACY000002', 'NZ7K2H', 'Don', 'mark.don@example.com', 'flight_cancelled', '',
                 '2026-01-05T10:00:00Z', 1234.0, 'NZD');
        """)
        connection.commit()
        connection.close()
        store = server.ApplicationStore(legacy)
        record = store.request_for_booking("NZ7K2H")
        self.assertEqual(record["phone"], "")
        self.assertEqual(record["contact"], {"phone": "", "email": "mark.don@example.com"})
        self.assertEqual(record["paymentMethod"], {"type": "card", "brand": "Visa", "last4": "4242"})


if __name__ == "__main__":
    unittest.main()
