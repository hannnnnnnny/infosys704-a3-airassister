"""SQLite storage: additive migration, idempotent seed, idempotent submissions and decisions."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from refund_support import PASSENGER, QUOTE, server


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="runtime-", dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def store(self, name="data.sqlite3"):
        return server.ApplicationStore(self.folder / name)

    def test_seed_is_idempotent_and_labelled_as_a_recorded_snapshot(self):
        store = self.store()
        self.store()
        seeded = [record for record in store.staff_requests() if record["reference"] == "AF-DEMO000001"]
        self.assertEqual(len(seeded), 1)
        record = seeded[0]
        self.assertEqual((record["passengerName"], record["bookingReference"]), ("Minh Nguyen", "NZ9P4K"))
        self.assertEqual((record["sapDocument"], record["amount"], record["currency"]), ("60000049", 400.0, "USD"))
        self.assertEqual((record["sapStatus"], record["route"], record["status"]), ("A", "specialist", "pending"))
        self.assertEqual(record["quoteSource"], "SAP snapshot captured 2026-10-14")
        self.assertEqual(record["quoteFetchedAt"], "2026-10-14T00:00:00Z")

    def test_legacy_schema_still_loads_after_an_additive_migration(self):
        legacy = self.folder / "legacy.sqlite3"
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
                ('AF-LEGACY000001', 'NZ7K2H', 'Don', 'mark.don@example.com', 'flight_cancelled', '',
                 '2026-01-05T10:00:00Z', 1234.0, 'NZD');
        """)
        connection.commit()
        connection.close()
        store = server.ApplicationStore(legacy)
        records = {record["reference"]: record for record in store.staff_requests()}
        self.assertIn("AF-LEGACY000001", records)
        legacy_record = records["AF-LEGACY000001"]
        self.assertEqual((legacy_record["bookingReference"], legacy_record["status"]), ("NZ7K2H", "pending"))
        self.assertIsNone(legacy_record["amount"])
        self.assertEqual(legacy_record["refundType"], "full")
        self.assertEqual(legacy_record["version"], 1)
        self.assertEqual(legacy_record["route"], "specialist")
        self.assertEqual(store.request_for_booking("NZ7K2H")["reference"], "AF-LEGACY000001")

    def test_submission_snapshots_the_quote_and_is_idempotent(self):
        store = self.store()
        key = "6f1d1f5e-6a1e-4f2a-9a2e-2f1a5c3b7d90"
        record, created = store.submit_request(booking_reference="NZ7K2H", passenger_name="Mark Don",
                                               email="mark.don@example.com", quote=QUOTE,
                                               request_key=key, quote_source="live")
        self.assertTrue(created)
        self.assertEqual((record["amount"], record["currency"], record["sapDocument"]), (250.0, "NZD", "60000073"))
        again, created_again = store.submit_request(booking_reference="NZ7K2H", passenger_name="Mark Don",
                                                    email="mark.don@example.com", quote=QUOTE,
                                                    request_key=key, quote_source="live")
        self.assertFalse(created_again)
        self.assertEqual(again, record)
        # One request per booking, even with a fresh key.
        other, created_other = store.submit_request(booking_reference="NZ7K2H", passenger_name="Mark Don",
                                                    email="another@example.com", quote=QUOTE,
                                                    request_key="11111111-1111-1111-1111-111111111111",
                                                    quote_source="live")
        self.assertFalse(created_other)
        self.assertEqual(other["reference"], record["reference"])
        self.assertEqual(len([item for item in store.staff_requests()
                              if item["bookingReference"] == "NZ7K2H"]), 1)

    def test_request_key_cannot_be_reused_for_a_different_payload(self):
        store = self.store()
        key = "22222222-2222-2222-2222-222222222222"
        store.submit_request(booking_reference="NZ7K2H", passenger_name="Mark Don",
                             email="mark.don@example.com", quote=QUOTE, request_key=key, quote_source="live")
        with self.assertRaises(server.APIError) as conflict:
            store.find_submission(key, server.submission_fingerprint("NZ9P4K", "someone@example.com"))
        self.assertEqual((conflict.exception.status, conflict.exception.code), (409, "IDEMPOTENCY_CONFLICT"))

    def test_decision_records_an_immutable_event_and_bumps_the_version(self):
        store = self.store()
        record, _ = store.submit_request(booking_reference="NZ7K2H", passenger_name="Mark Don",
                                         email="mark.don@example.com", quote=QUOTE,
                                         request_key="33333333-3333-3333-3333-333333333333", quote_source="live")
        decided = store.decide(record["reference"], decision="decline", note="Duplicate booking.",
                               version=record["version"], staff_name="Refunds team")
        self.assertEqual((decided["status"], decided["version"]), ("declined", 2))
        self.assertEqual(decided["events"][-1]["staff"], "Refunds team")
        with self.assertRaises(server.APIError) as stale:
            store.decide(record["reference"], decision="approve", note="", version=1, staff_name="Refunds team")
        self.assertEqual(stale.exception.code, "VERSION_CONFLICT")
        with self.assertRaises(server.APIError) as decided_again:
            store.decide(record["reference"], decision="approve", note="", version=2, staff_name="Refunds team")
        self.assertEqual(decided_again.exception.code, "REQUEST_ALREADY_DECIDED")

    def test_deciding_an_unknown_reference_is_not_found(self):
        store = self.store()
        with self.assertRaises(server.APIError) as missing:
            store.decide("AF-000000000000", decision="approve", note="", version=1, staff_name="Refunds team")
        self.assertEqual((missing.exception.status, missing.exception.code), (404, "REQUEST_NOT_FOUND"))


if __name__ == "__main__":
    unittest.main()
