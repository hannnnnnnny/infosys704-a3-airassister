"""Shared helpers for the AirAssist backend tests.

Not named test_*, so unittest discovery does not collect it. The app directory is added to
sys.path so every test file shares one import of the prototype server module.
"""
import json
import sys
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import server  # noqa: E402

PASSENGER = "mark.don"
STAFF = "admin"
PASSENGER_PASSWORD = "passenger-test-password"
STAFF_PASSWORD = "staff-test-password"

SAP_RECORD = {
    "id": "60000073", "totalNetAmount": 250.0, "currency": "NZD",
    "referenceDocument": "60000001", "referenceDocumentCategory": "H",
    "processStatusCode": "A", "approvalStatusCode": "", "createdAt": "2026-10-01",
    "source": {"mode": "live", "label": "SAP test service", "fetchedAt": "2026-10-14T00:00:00Z"},
}

QUOTE = {
    "sapDocument": "60000073", "amount": 250.0, "currency": "NZD",
    "processStatus": "A", "fetchedAt": "2026-10-14T00:00:00Z",
}


def make_auth(*, deployed=False, passenger=PASSENGER_PASSWORD, staff=STAFF_PASSWORD,
              secret=b"test-session-secret", iterations=1000):
    return server.AuthConfig({PASSENGER: passenger, STAFF: staff}, secret,
                             deployed=deployed, iterations=iterations)


def public_dir(folder):
    public = Path(folder) / "public"
    public.mkdir(parents=True, exist_ok=True)
    (public / "index.html").write_text("test-public-page", encoding="utf-8")
    return public


class FakeSAP:
    """Controllable stand-in for SAPClient that records every read."""

    def __init__(self, record=None):
        self.config = server.SAPConfig()
        self.record = dict(record if record is not None else SAP_RECORD)
        self.error = None
        self.calls = []

    def get_credit_memo(self, identifier):
        self.calls.append(identifier)
        if self.error is not None:
            raise self.error
        record = dict(self.record)
        record["id"] = str(identifier)
        return record


class APIServer:
    """Runs the real handler on a loopback socket for HTTP contract tests."""

    def __init__(self, store, sap, public, auth):
        self.httpd = server.make_server(store, sap, public_dir=public, port=0, auth=auth)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)

    def raw(self, path, data, content_type="application/json", headers=None):
        request_headers = {"Content-Type": content_type, **(headers or {})}
        request = Request(self.base + path, data=data, headers=request_headers)
        try:
            response = urlopen(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, response.read()

    def call(self, path, body=None, headers=None, method=None):
        request_headers = {"Content-Type": "application/json"} if body is not None else {}
        request_headers.update(headers or {})
        data = json.dumps(body).encode() if body is not None else None
        request = Request(self.base + path, data=data, headers=request_headers, method=method)
        try:
            response = urlopen(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, response.read()

    def json_call(self, path, body=None, headers=None, method=None):
        status, response_headers, raw = self.call(path, body, headers, method)
        return status, response_headers, json.loads(raw)

    def login(self, username, password, **kwargs):
        status, _, result = self.json_call("/api/auth/login", {"username": username, "password": password}, **kwargs)
        if status != 200:
            raise AssertionError(f"login failed for {username!r}: {status} {result}")
        return result
