"""Private, conditionally written SQLite snapshots for the coursework demo."""
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener

try:
    from .server import APIError, ApplicationStore, NoRedirect
except ImportError:
    from server import APIError, ApplicationStore, NoRedirect

MAX_SNAPSHOT_BYTES = 5 * 1024 * 1024


class SnapshotConflict(Exception):
    """A newer snapshot must be loaded before retrying the operation."""


def unavailable():
    return APIError(503, "STORAGE_UNAVAILABLE", "Demo storage is unavailable. Please retry shortly.")


class BlobSnapshots:
    def __init__(self, token=None, opener=None):
        self.token = token or os.environ.get("BLOB_READ_WRITE_TOKEN", "")
        match = re.fullmatch(r"vercel_blob_rw_([A-Za-z0-9]+)_[A-Za-z0-9]+", self.token)
        self.store_id = match.group(1).lower() if match else ""
        self.opener = opener or build_opener(NoRedirect())
        self.pathname = "airassist/demo.sqlite3"

    def request(self, url, *, body=None, headers=None):
        if not self.store_id:
            raise unavailable()
        auth = {"Authorization": "Bearer " + self.token, **(headers or {})}
        method = "PUT" if body is not None else "GET"
        return self.opener.open(Request(url, data=body, headers=auth, method=method), timeout=8)

    def read(self):
        url = f"https://{self.store_id}.private.blob.vercel-storage.com/{self.pathname}?cache=0"
        try:
            with self.request(url) as response:
                body = response.read(MAX_SNAPSHOT_BYTES + 1)
                etag = response.headers.get("ETag")
                if len(body) > MAX_SNAPSHOT_BYTES or not etag or not body.startswith(b"SQLite format 3\0"):
                    raise unavailable()
                return body, etag
        except HTTPError as error:
            if error.code == 404:
                return None, None
            raise unavailable() from None
        except (URLError, TimeoutError, OSError):
            raise unavailable() from None

    def write(self, body, etag):
        if len(body) > MAX_SNAPSHOT_BYTES:
            raise APIError(503, "STORAGE_FULL", "This demo has reached its storage limit.")
        # Match the official Blob SDK protocol; ETags prevent cross-instance lost updates.
        headers = {
            "x-api-version": "12", "x-vercel-blob-access": "private",
            "x-add-random-suffix": "0", "x-allow-overwrite": "1" if etag else "0",
            "x-content-type": "application/octet-stream", "x-cache-control-max-age": "60",
        }
        if etag:
            headers["x-if-match"] = etag
        url = "https://vercel.com/api/blob/?" + urlencode({"pathname": self.pathname})
        try:
            with self.request(url, body=body, headers=headers) as response:
                response.read(16_384)
        except HTTPError as error:
            payload = error.read(16_384)
            try:
                code = json.loads(payload).get("error", {}).get("code")
            except (ValueError, AttributeError):
                code = None
            if error.code == 412 or code == "precondition_failed":
                raise SnapshotConflict() from None
            # Initial creation is also conditional: another request may create it first.
            if not etag and error.code == 400 and b"already exists" in payload.lower():
                raise SnapshotConflict() from None
            raise unavailable() from None
        except (URLError, TimeoutError, OSError):
            raise unavailable() from None


class CloudStore:
    def __init__(self, snapshots=None):
        self.snapshots = snapshots if snapshots is not None else BlobSnapshots()

    def run(self, method, *args, write=False, **kwargs):
        for attempt in range(3):
            body, etag = self.snapshots.read()
            with tempfile.TemporaryDirectory(prefix="airassist-") as directory:
                path = Path(directory) / "demo.sqlite3"
                if body is not None:
                    path.write_bytes(body)
                store = ApplicationStore(path)
                result = getattr(store, method)(*args, **kwargs)
                # A cold snapshot is seeded on first touch, so even reads persist the demo request.
                if not write and body is not None:
                    return result
                with store.connect() as connection:
                    updated = connection.serialize()
                try:
                    self.snapshots.write(updated, etag)
                    return result
                except SnapshotConflict:
                    if attempt == 2:
                        raise APIError(409, "STORAGE_CONFLICT", "Another demo request changed storage. Please retry.") from None
        raise unavailable()

    def find_submission(self, request_key, fingerprint):
        return self.run("find_submission", request_key, fingerprint)

    def request_for_booking(self, booking_reference):
        return self.run("request_for_booking", booking_reference)

    def staff_requests(self):
        return self.run("staff_requests")

    def submit_request(self, **kwargs):
        return self.run("submit_request", write=True, **kwargs)

    def decide(self, reference, **kwargs):
        return self.run("decide", reference, write=True, **kwargs)
