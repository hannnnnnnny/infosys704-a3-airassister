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

    def test_demo_reset_empties_legacy_tables_and_reseeds_on_an_old_schema(self):
        legacy = self.folder / "old-schema.sqlite3"
        connection = sqlite3.connect(legacy)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript("""
            CREATE TABLE refund_requests (
                public_reference TEXT PRIMARY KEY, booking_reference TEXT NOT NULL, last_name TEXT NOT NULL,
                email TEXT NOT NULL, reason TEXT NOT NULL, details TEXT NOT NULL, created_at TEXT NOT NULL,
                ticket_value REAL NOT NULL, currency TEXT NOT NULL, UNIQUE(booking_reference, email));
            CREATE TABLE submission_keys (
                request_key TEXT PRIMARY KEY, payload_hash TEXT NOT NULL,
                public_reference TEXT NOT NULL REFERENCES refund_requests(public_reference));
            CREATE TABLE review_state (
                booking_reference TEXT PRIMARY KEY, review_status TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE review_financial_references (
                public_reference TEXT PRIMARY KEY, sap_document TEXT NOT NULL,
                FOREIGN KEY (public_reference) REFERENCES refund_requests(public_reference));
            INSERT INTO refund_requests VALUES
                ('AF-OLD00000001', 'NZ7K2H', 'Don', 'mark.don@example.com', 'flight_cancelled', '',
                 '2026-01-05T10:00:00Z', 1234.0, 'NZD');
            INSERT INTO submission_keys VALUES ('44444444-4444-4444-4444-444444444444', 'hash', 'AF-OLD00000001');
            INSERT INTO review_state VALUES ('NZ7K2H', 'queued', '2026-01-05T10:00:00Z');
            INSERT INTO review_financial_references VALUES ('AF-OLD00000001', '60000073');
        """)
        connection.commit()
        connection.close()
        store = server.ApplicationStore(legacy)
        records = store.reset_demo()
        connection = sqlite3.connect(legacy)
        try:
            remaining = {table: connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                         for table in ("submission_keys", "review_state", "review_financial_references")}
        finally:
            connection.close()
        self.assertEqual(remaining, {"submission_keys": 0, "review_state": 0, "review_financial_references": 0})
        self.assertNotIn("AF-OLD00000001", [record["reference"] for record in records])
        seeded = [record for record in records if record["reference"] == "AF-DEMO000001"]
        self.assertEqual(len(seeded), 1)
        self.assertEqual((seeded[0]["passengerName"], seeded[0]["status"]), ("Minh Nguyen", "pending"))


class MultiTripSeedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="runtime-", dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def store(self, name="data.sqlite3"):
        return server.ApplicationStore(self.folder / name)

    def test_new_seeds_are_idempotent_with_fixed_references(self):
        store = self.store()
        self.store()
        records = {record["reference"]: record for record in store.staff_requests()}
        for reference in ("AF-DEMO000001", "AF-DEMO000002", "AF-DEMO000003"):
            self.assertIn(reference, records)
        pending = records["AF-DEMO000002"]
        self.assertEqual((pending["bookingReference"], pending["passengerName"]), ("NZ5R8M", "Mark Don"))
        self.assertEqual((pending["sapDocument"], pending["amount"], pending["currency"]),
                         ("60000062", 175.50, "USD"))
        self.assertEqual((pending["sapStatus"], pending["route"], pending["status"]),
                         ("C", "specialist", "pending"))
        self.assertEqual(pending["quoteSource"], "SAP snapshot captured 2026-10-14")
        approved = records["AF-DEMO000003"]
        self.assertEqual((approved["bookingReference"], approved["passengerName"]), ("NZ2W6B", "Mark Don"))
        self.assertEqual((approved["sapDocument"], approved["amount"]), ("60000026", 60.00))
        self.assertEqual((approved["sapStatus"], approved["route"], approved["status"]),
                         ("C", "specialist", "approved"))

    def test_demo_reset_restores_pending_and_approved_seeds(self):
        store = self.store()
        store.submit_request(booking_reference="NZ7K2H", passenger_name="Mark Don",
                             email="mark.don@example.com", quote=QUOTE,
                             request_key="55555555-5555-5555-5555-555555555555", quote_source="live")
        records = {record["reference"]: record for record in store.reset_demo()}
        self.assertEqual(records["AF-DEMO000002"]["status"], "pending")
        self.assertEqual(records["AF-DEMO000003"]["status"], "approved")
        self.assertIsNone(store.request_for_booking("NZ7K2H"))


if __name__ == "__main__":
    unittest.main()
