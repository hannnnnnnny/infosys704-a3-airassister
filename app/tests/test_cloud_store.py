"""Serverless snapshots must preserve records and reject concurrent overwrites."""
import sys
import threading
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class MemorySnapshots:
    """An in-memory stand-in for the private Blob snapshot store."""

    def __init__(self):
        self.body, self.version = None, 0
        self.lock = threading.Lock()
        self.conflict_once = False

    def read(self):
        with self.lock:
            return self.body, str(self.version) if self.body else None

    def write(self, body, etag):
        from cloud_store import SnapshotConflict
        with self.lock:
            current = str(self.version) if self.body else None
            if self.conflict_once:
                self.conflict_once = False
                raise SnapshotConflict()
            if current != etag:
                raise SnapshotConflict()
            self.body, self.version = body, self.version + 1


def submission(email="mark.don@example.com", booking="NZ7K2H", request_key=None):
    return {
        "booking_reference": booking, "passenger_name": "Mark Don", "email": email,
        "quote": {"sapDocument": "60000073", "amount": 250.0, "currency": "NZD",
                  "processStatus": "A", "fetchedAt": "2026-10-14T00:00:00Z"},
        "request_key": request_key or str(uuid.uuid4()), "quote_source": "live",
    }


class CloudStoreTests(unittest.TestCase):
    def store(self, snapshots):
        import cloud_store
        return cloud_store.CloudStore(snapshots)

    def test_cloud_store_is_available(self):
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec("cloud_store"))

    def test_cold_start_seeds_and_retains_submitted_requests(self):
        snapshots = MemorySnapshots()
        seeded = self.store(snapshots).staff_requests()
        self.assertEqual([record["reference"] for record in seeded], ["AF-DEMO000001"])
        record, created = self.store(snapshots).submit_request(**submission())
        self.assertTrue(created)
        restored = self.store(snapshots).request_for_booking("NZ7K2H")
        self.assertEqual(restored, record)
        self.assertEqual(len(self.store(snapshots).staff_requests()), 2)

    def test_duplicate_and_conflict_retry_preserve_the_original_request(self):
        snapshots = MemorySnapshots()
        snapshots.conflict_once = True
        payload = submission(request_key="44444444-4444-4444-4444-444444444444")
        original, created = self.store(snapshots).submit_request(**payload)
        self.assertTrue(created)
        duplicate, created_again = self.store(snapshots).submit_request(**payload)
        self.assertFalse(created_again)
        self.assertEqual(duplicate, original)

    def test_decisions_survive_a_new_store(self):
        snapshots = MemorySnapshots()
        record, _ = self.store(snapshots).submit_request(**submission(request_key=str(uuid.uuid4())))
        decided = self.store(snapshots).decide(record["reference"], decision="approve", note="",
                                               version=record["version"], staff_name="Refunds team")
        self.assertEqual(decided["status"], "approved")
        persisted = self.store(snapshots).request_for_booking("NZ7K2H")
        self.assertEqual(persisted["status"], "approved")
        self.assertEqual(persisted["events"][-1]["staff"], "Refunds team")

    def test_parallel_submissions_for_one_booking_agree_on_one_request(self):
        from concurrent.futures import ThreadPoolExecutor
        snapshots = MemorySnapshots()
        with ThreadPoolExecutor(max_workers=2) as executor:
            records = list(executor.map(
                lambda email: self.store(snapshots).submit_request(**submission(email=email))[0],
                ["one@example.com", "two@example.com"],
            ))
        self.assertEqual(len({record["reference"] for record in records}), 1)
        self.assertEqual(len(self.store(snapshots).staff_requests()), 2)

    def test_blob_upload_uses_put_instead_of_post(self):
        from cloud_store import BlobSnapshots
        from unittest.mock import Mock
        opener = Mock()
        snapshots = BlobSnapshots("vercel_blob_rw_teststore_testtoken", opener)
        snapshots.request("https://vercel.com/api/blob/", body=b"snapshot")
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_method(), "PUT")


if __name__ == "__main__":
    unittest.main()
