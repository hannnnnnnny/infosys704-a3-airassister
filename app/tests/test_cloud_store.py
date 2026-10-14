"""Serverless copies must preserve records and reject concurrent overwrites."""
import sys
import threading
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class MemorySnapshots:
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


def application(email="demo@example.com"):
    return server.validate_application({
        "bookingReference": "NZ7K2H", "lastName": "Taylor", "email": email,
        "reason": "flight_cancelled", "details": "", "acknowledged": True,
        "requestKey": str(uuid.uuid4()),
    })


class CloudStoreTests(unittest.TestCase):
    def store(self, snapshots):
        import cloud_store
        return cloud_store.CloudStore(snapshots)

    def test_cloud_store_is_available(self):
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec("cloud_store"))

    def test_cold_start_retains_record_and_rejects_wrong_owner(self):
        snapshots = MemorySnapshots()
        record, created = self.store(snapshots).submit(application())
        self.assertTrue(created)
        restored = self.store(snapshots).find(record["publicReference"], record["email"])
        self.assertEqual(restored, record)
        with self.assertRaises(server.APIError) as error:
            self.store(snapshots).find(record["publicReference"], "wrong@example.com")
        self.assertEqual(error.exception.status, 404)

    def test_duplicate_and_conflict_retry_preserve_original_application(self):
        snapshots = MemorySnapshots()
        snapshots.conflict_once = True
        original, _ = self.store(snapshots).submit(application())
        duplicate, created = self.store(snapshots).submit(application())
        self.assertFalse(created)
        self.assertEqual(duplicate, original)

    def test_parallel_submissions_do_not_lose_an_application(self):
        from concurrent.futures import ThreadPoolExecutor
        snapshots = MemorySnapshots()
        with ThreadPoolExecutor(max_workers=2) as executor:
            records = list(executor.map(
                lambda email: self.store(snapshots).submit(application(email))[0],
                ["one@example.com", "two@example.com"],
            ))
        for record in records:
            found = self.store(snapshots).find(record["publicReference"], record["email"])
            self.assertEqual(found, record)


if __name__ == "__main__":
    unittest.main()
