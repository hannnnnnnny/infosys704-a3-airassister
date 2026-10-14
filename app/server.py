"""AirAssist course prototype: sign-in, live SAP refund quotes and human refund decisions.

Run with Python 3.10+: python server.py
Only public/ is served. The SQLite database and personal .env stay server-side.
No payment is made and nothing is written to SAP.
"""

from __future__ import annotations

import argparse
import base64
import collections
import gzip
import hashlib
import hmac
import io
import json
import logging
import math
import mimetypes
import os
import re
import secrets
import sqlite3
import ssl
import threading
import time
import uuid
import zlib
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener


BASE_DIR = Path(__file__).resolve().parent
MAX_BODY_BYTES = 16_384
MAX_SAP_BYTES = 1_048_576
MAX_DECISION_NOTE = 500
TOKEN_SECONDS = 7_200
LOGIN_WINDOW_SECONDS = 300
LOGIN_MAX_FAILURES = 5
PBKDF2_ITERATIONS = 120_000
REFERENCE_PATTERN = re.compile(r"AF-[A-Z0-9]{4,20}")
DECISION_PATH = re.compile(r"^/api/staff/requests/([A-Za-z0-9-]{1,40})/decision$")
SAP_HOSTS = {"api.sap.com", "sandbox.api.sap.com"}
PERSONAL_ENV_KEYS = {
    "AIRASSIST_SAP_MODE", "AIRASSIST_SAP_BASE_URL", "AIRASSIST_SAP_API_KEY",
    "AIRASSIST_SAP_ACCOUNT_TYPE", "AIRASSIST_DATABASE", "AIRASSIST_PORT",
    "AIRASSIST_PASSENGER_PASSWORD", "AIRASSIST_STAFF_PASSWORD", "AIRASSIST_SESSION_SECRET",
}
LOGGER = logging.getLogger("airassist")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class APIError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def load_personal_env(path: Path = BASE_DIR / ".env") -> None:
    """Read only the project's explicit personal configuration, without expansion."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip()
        if name not in PERSONAL_ENV_KEYS:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(name, value)


def valid_sap_base(value: str) -> bool:
    try:
        url = urlsplit(value)
        return (
            url.scheme == "https" and url.hostname in SAP_HOSTS
            and url.port in (None, 443) and not url.username and not url.password
            and not url.query and not url.fragment
            and url.path.startswith("/") and len(url.path) > 1
            and not any(ord(character) <= 32 or character == "\\" for character in value)
        )
    except ValueError:
        return False


@dataclass(frozen=True)
class SAPConfig:
    mode: str = "unconfigured"
    base_url: str = ""
    api_key: str = ""
    account_type: str = "personal"

    @classmethod
    def from_environment(cls) -> "SAPConfig":
        mode = os.environ.get("AIRASSIST_SAP_MODE", "unconfigured").strip().lower()
        return cls(
            mode=mode if mode in {"unconfigured", "live"} else "unconfigured",
            base_url=os.environ.get("AIRASSIST_SAP_BASE_URL", "").strip().rstrip("/"),
            api_key=os.environ.get("AIRASSIST_SAP_API_KEY", "").strip(),
            account_type=os.environ.get("AIRASSIST_SAP_ACCOUNT_TYPE", "personal").strip().lower(),
        )

    @property
    def configured(self) -> bool:
        return (
            self.mode == "live" and self.account_type == "personal"
            and valid_sap_base(self.base_url) and bool(self.api_key)
            and len(self.api_key) <= 4096 and "\r" not in self.api_key and "\n" not in self.api_key
        )


# Sample bookings. Every journey is a synthetic, airline-cancelled direct booking with a linked
# SAP credit memo request document. No real traveller data is used.
BOOKINGS = {
    "NZ7K2H": {
        "reference": "NZ7K2H", "lastName": "Don", "passengerName": "Mark Don",
        "flight": "NZ6", "fromCode": "AKL", "fromCity": "Auckland",
        "toCode": "LAX", "toCity": "Los Angeles", "date": "2026-10-28",
        "cabin": "Economy", "flightStatus": "cancelled", "channel": "direct",
        "sapCreditMemoRequest": "60000073",
    },
    "NZ9P4K": {
        "reference": "NZ9P4K", "lastName": "Nguyen", "passengerName": "Minh Nguyen",
        "flight": "NZ2", "fromCode": "AKL", "fromCity": "Auckland",
        "toCode": "LAX", "toCity": "Los Angeles", "date": "2026-10-29",
        "cabin": "Economy", "flightStatus": "cancelled", "channel": "direct",
        "sapCreditMemoRequest": "60000049",
    },
}

# Demo accounts. Passwords are never stored in the repository; each account names the local
# configuration variable that supplies its password.
ACCOUNTS = {
    "mark.don": {
        "role": "passenger", "displayName": "Mark Don", "booking": "NZ7K2H",
        "passwordEnv": "AIRASSIST_PASSENGER_PASSWORD",
    },
    "admin": {
        "role": "staff", "displayName": "Refunds team",
        "passwordEnv": "AIRASSIST_STAFF_PASSWORD",
    },
}

SEED_REFERENCE = "AF-DEMO000001"
SEED_EMAIL = "minh.nguyen@example.com"
# Recorded SAP snapshot for the seeded demo request. It is not a live read and is labelled as such.
SEED_QUOTE = {
    "sapDocument": "60000049",
    "amount": 400.0,
    "currency": "USD",
    "processStatus": "A",
    "fetchedAt": "2026-10-14T00:00:00Z",
    "source": "SAP snapshot captured 2026-10-14",
}


def text_field(value, name: str, maximum: int, *, required: bool = True) -> str:
    if not isinstance(value, str):
        raise APIError(400, "INVALID_INPUT", f"Provide a valid {name}.")
    value = value.strip()
    if (required and not value) or len(value) > maximum or any(
        ord(char) < 32 and char not in "\n\t" for char in value
    ):
        raise APIError(400, "INVALID_INPUT", f"Provide a valid {name}.")
    return value


def normalized_email(value) -> str:
    value = text_field(value, "email address", 254).casefold()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise APIError(400, "INVALID_INPUT", "Provide a valid email address.")
    return value


def validate_login(payload) -> dict:
    if not isinstance(payload, dict):
        raise APIError(400, "INVALID_INPUT", "Provide a JSON object with username and password.")
    username, password = payload.get("username"), payload.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        raise APIError(400, "INVALID_INPUT", "Provide a username and password.")
    username = username.strip().lower()
    if not username or len(username) > 80 or any(ord(char) < 32 for char in username):
        raise APIError(400, "INVALID_INPUT", "Provide a username and password.")
    if not password or len(password) > 200:
        raise APIError(400, "INVALID_INPUT", "Provide a username and password.")
    return {"username": username, "password": password}


def validate_submission(payload) -> dict:
    if not isinstance(payload, dict):
        raise APIError(400, "INVALID_INPUT", "Provide a JSON object for the refund request.")
    email = normalized_email(payload.get("email"))
    if payload.get("confirmed") is not True:
        raise APIError(400, "CONFIRMATION_REQUIRED", "Confirm the full refund request before submitting.")
    request_key = text_field(payload.get("requestKey"), "request key", 36)
    try:
        request_key = str(uuid.UUID(request_key))
    except ValueError:
        raise APIError(400, "INVALID_INPUT", "Provide a valid request key.") from None
    return {"email": email, "requestKey": request_key}


def validate_decision(payload) -> dict:
    if not isinstance(payload, dict):
        raise APIError(400, "INVALID_INPUT", "Provide a JSON object for the decision.")
    decision = payload.get("decision")
    if decision not in {"approve", "decline"}:
        raise APIError(400, "INVALID_INPUT", "Choose approve or decline.")
    note = payload.get("note", "")
    if not isinstance(note, str) or len(note) > MAX_DECISION_NOTE or any(
        ord(char) < 32 and char not in "\n\t" for char in note
    ):
        raise APIError(400, "INVALID_INPUT", "Provide a decision note of up to 500 characters.")
    note = note.strip()
    if decision == "decline" and not note:
        raise APIError(400, "INVALID_INPUT", "A note is required when declining a request.")
    version = payload.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise APIError(400, "INVALID_INPUT", "Provide the current request version as a positive integer.")
    return {"decision": decision, "note": note, "version": version}


def submission_fingerprint(booking_reference: str, email: str) -> str:
    payload = json.dumps(
        {"bookingReference": booking_reference, "email": email},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_quote(record: dict) -> dict:
    """Documentary refund quote copied from one live, read-only SAP credit memo request."""
    return {
        "sapDocument": record["id"],
        "amount": record["totalNetAmount"],
        "currency": record["currency"],
        "processStatus": record["processStatusCode"],
        "fetchedAt": record["source"]["fetchedAt"],
    }


def decide_route(booking: dict, process_status, amount) -> str:
    amount_is_number = (
        isinstance(amount, (int, float)) and not isinstance(amount, bool) and math.isfinite(amount)
    )
    if (
        booking["channel"] == "direct" and booking["flightStatus"] == "cancelled"
        and process_status == "A" and amount_is_number and amount <= 300
    ):
        return "fast_track"
    return "specialist"


def booking_view(booking: dict) -> dict:
    return {
        "reference": booking["reference"], "passengerName": booking["passengerName"],
        "flight": booking["flight"], "fromCode": booking["fromCode"], "fromCity": booking["fromCity"],
        "toCode": booking["toCode"], "toCity": booking["toCity"], "date": booking["date"],
        "cabin": booking["cabin"], "flightStatus": booking["flightStatus"],
        "channel": booking["channel"], "sapCreditMemoRequest": booking["sapCreditMemoRequest"],
    }


def flight_view(booking: dict) -> dict:
    return {
        "flight": booking["flight"], "fromCode": booking["fromCode"], "fromCity": booking["fromCity"],
        "toCode": booking["toCode"], "toCity": booking["toCity"], "date": booking["date"],
        "cabin": booking["cabin"], "flightStatus": booking["flightStatus"],
    }


def _password_digest(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)


class AuthConfig:
    """In-memory accounts: only salted password hashes and a signed-token secret are kept."""

    def __init__(self, passwords: dict, session_secret: bytes, *, deployed: bool = False,
                 iterations: int = PBKDF2_ITERATIONS):
        self.deployed = deployed
        self.session_secret = session_secret
        self.iterations = iterations
        self.accounts = {}
        for username, meta in ACCOUNTS.items():
            password = passwords.get(username)
            salt = secrets.token_bytes(16)
            digest = _password_digest(password, salt, iterations) if password else b""
            self.accounts[username] = {**meta, "salt": salt, "hash": digest, "available": bool(password)}
        self._dummy_salt = secrets.token_bytes(16)
        self._dummy_hash = _password_digest(secrets.token_hex(16), self._dummy_salt, iterations)
        self._lock = threading.Lock()
        self._failures: dict = {}

    # --- rate limiting (keyed by username and client address) ---------------------------------
    @staticmethod
    def _rate_key(username: str, client: str) -> str:
        return username + "|" + client

    def _prune(self, failures: collections.deque, now: float) -> None:
        while failures and now - failures[0] > LOGIN_WINDOW_SECONDS:
            failures.popleft()

    def check_rate_limit(self, username: str, client: str) -> None:
        now = time.time()
        with self._lock:
            failures = self._failures.get(self._rate_key(username, client))
            if not failures:
                return
            self._prune(failures, now)
            if not failures:
                self._failures.pop(self._rate_key(username, client), None)
                return
            if len(failures) >= LOGIN_MAX_FAILURES:
                raise APIError(429, "TOO_MANY_ATTEMPTS", "Too many sign-in attempts. Try again in a few minutes.")

    def record_failure(self, username: str, client: str) -> None:
        now = time.time()
        with self._lock:
            failures = self._failures.setdefault(self._rate_key(username, client), collections.deque())
            self._prune(failures, now)
            failures.append(now)

    def clear_failures(self, username: str, client: str) -> None:
        with self._lock:
            self._failures.pop(self._rate_key(username, client), None)

    # --- authentication -----------------------------------------------------------------------
    def authenticate(self, username: str, password: str, client: str) -> dict:
        self.check_rate_limit(username, client)
        account = self.accounts.get(username)
        salt = account["salt"] if account else self._dummy_salt
        expected = account["hash"] if account else self._dummy_hash
        candidate = _password_digest(password, salt, self.iterations)
        matched = secrets.compare_digest(candidate, expected)
        if account is None or not account["available"] or not matched:
            self.record_failure(username, client)
            if account is not None and not account["available"]:
                raise APIError(503, "SIGNIN_UNAVAILABLE", "Sign-in is not configured for this account on this deployment.")
            raise APIError(401, "INVALID_CREDENTIALS", "Incorrect username or password.")
        self.clear_failures(username, client)
        return account

    # --- stateless signed tokens --------------------------------------------------------------
    def issue_token(self, account: dict, subject: str, now: float | None = None) -> str:
        expires = int(now if now is not None else time.time()) + TOKEN_SECONDS
        payload = json.dumps(
            {"role": account["role"], "subject": subject, "exp": expires},
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        body = base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")
        signature = hmac.new(self.session_secret, body.encode("ascii"), hashlib.sha256).hexdigest()
        return body + "." + signature

    def verify_token(self, token, now: float | None = None) -> dict:
        if not isinstance(token, str) or not token or len(token) > 4096 or token.count(".") != 1:
            raise APIError(401, "UNAUTHENTICATED", "Sign in to continue.")
        body, signature = token.split(".")
        expected = hmac.new(self.session_secret, body.encode("ascii"), hashlib.sha256).hexdigest()
        if not secrets.compare_digest(signature, expected):
            raise APIError(401, "UNAUTHENTICATED", "Sign in to continue.")
        try:
            payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise APIError(401, "UNAUTHENTICATED", "Sign in to continue.") from None
        if (not isinstance(payload, dict) or set(payload) != {"role", "subject", "exp"}
                or payload.get("role") not in {"passenger", "staff"}
                or not isinstance(payload.get("subject"), str)
                or isinstance(payload.get("exp"), bool) or not isinstance(payload.get("exp"), int)):
            raise APIError(401, "UNAUTHENTICATED", "Sign in to continue.")
        if payload["exp"] <= int(now if now is not None else time.time()):
            raise APIError(401, "SESSION_EXPIRED", "Your sign-in has expired. Sign in again.")
        account = self.accounts.get(payload["subject"])
        if account is None or account["role"] != payload["role"]:
            raise APIError(401, "UNAUTHENTICATED", "Sign in to continue.")
        return payload


def build_auth(*, deployed: bool = False, passwords: dict | None = None,
               session_secret: str | None = None) -> tuple[AuthConfig, dict]:
    """Resolve account passwords and the token secret; return the config and any generated passwords."""
    generated: dict = {}
    resolved: dict = {}
    for username, meta in ACCOUNTS.items():
        if passwords is not None:
            value = passwords.get(username) or None
        else:
            value = os.environ.get(meta["passwordEnv"], "").strip() or None
        if value is None and not deployed:
            value = secrets.token_urlsafe(12)
            generated[meta["passwordEnv"]] = value
        resolved[username] = value
    if session_secret is None:
        session_secret = os.environ.get("AIRASSIST_SESSION_SECRET", "").strip() or None
    if session_secret is None:
        if deployed:
            session_secret = os.environ.get("BLOB_READ_WRITE_TOKEN", "").strip() or secrets.token_urlsafe(32)
        else:
            session_secret = secrets.token_urlsafe(32)
    return AuthConfig(resolved, session_secret.encode("utf-8"), deployed=deployed), generated


class ApplicationStore:
    # Columns added after the original prototype schema. Migration is additive only.
    ADDED_COLUMNS = (
        ("passenger_name", "TEXT"),
        ("refund_type", "TEXT"),
        ("sap_document", "TEXT"),
        ("amount", "REAL"),
        ("sap_process_status", "TEXT"),
        ("quote_fetched_at", "TEXT"),
        ("quote_source", "TEXT"),
        ("route", "TEXT"),
        ("request_status", "TEXT"),
        ("decision_note", "TEXT"),
        ("version", "INTEGER"),
        ("events", "TEXT"),
        ("updated_at", "TEXT"),
    )

    def __init__(self, path: Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS refund_requests (
                    public_reference TEXT PRIMARY KEY,
                    booking_reference TEXT NOT NULL,
                    last_name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    details TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    ticket_value REAL NOT NULL,
                    currency TEXT NOT NULL,
                    UNIQUE(booking_reference, email)
                );
                CREATE TABLE IF NOT EXISTS submission_keys (
                    request_key TEXT PRIMARY KEY,
                    payload_hash TEXT NOT NULL,
                    public_reference TEXT NOT NULL REFERENCES refund_requests(public_reference)
                );
            """)
            self._migrate(connection)
            self._seed(connection)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _migrate(self, connection) -> None:
        existing = {row["name"] for row in connection.execute("PRAGMA table_info(refund_requests)")}
        for name, kind in self.ADDED_COLUMNS:
            if name not in existing:
                connection.execute(f"ALTER TABLE refund_requests ADD COLUMN {name} {kind}")

    def _seed(self, connection) -> None:
        booking = BOOKINGS["NZ9P4K"]
        created_at = SEED_QUOTE["fetchedAt"]
        events = [{"type": "submitted", "at": created_at, "note": "Seeded demo request."}]
        route = decide_route(booking, SEED_QUOTE["processStatus"], SEED_QUOTE["amount"])
        connection.execute(
            "INSERT OR IGNORE INTO refund_requests ("
            " public_reference, booking_reference, last_name, email, reason, details, created_at,"
            " ticket_value, currency, passenger_name, refund_type, sap_document, amount,"
            " sap_process_status, quote_fetched_at, quote_source, route, request_status, decision_note,"
            " version, events, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (SEED_REFERENCE, booking["reference"], booking["lastName"], SEED_EMAIL, "flight_disruption", "",
             created_at, 0.0, SEED_QUOTE["currency"], booking["passengerName"], "full", SEED_QUOTE["sapDocument"],
             SEED_QUOTE["amount"], SEED_QUOTE["processStatus"], SEED_QUOTE["fetchedAt"], SEED_QUOTE["source"],
             route, "pending", "", 1, json.dumps(events, ensure_ascii=False), created_at),
        )

    @staticmethod
    def _record(row: sqlite3.Row) -> dict:
        booking = BOOKINGS.get(row["booking_reference"], {})
        version = row["version"] if row["version"] is not None else 1
        return {
            "reference": row["public_reference"],
            "bookingReference": row["booking_reference"],
            "passengerName": row["passenger_name"] or row["last_name"] or "Passenger",
            "email": row["email"],
            "reason": row["reason"],
            "refundType": row["refund_type"] or "full",
            "sapDocument": row["sap_document"],
            "sapStatus": row["sap_process_status"],
            "amount": row["amount"],
            "currency": row["currency"],
            "quoteFetchedAt": row["quote_fetched_at"],
            "quoteSource": row["quote_source"],
            "route": row["route"] or "specialist",
            "status": row["request_status"] or "pending",
            "decisionNote": row["decision_note"] or "",
            "version": version,
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"] or row["created_at"],
            "flight": flight_view(booking) if booking else None,
            "events": json.loads(row["events"]) if row["events"] else [],
        }

    def find_submission(self, request_key: str, fingerprint: str):
        with self.connect() as connection:
            connection.execute("BEGIN")
            key_row = connection.execute(
                "SELECT payload_hash, public_reference FROM submission_keys WHERE request_key=?", (request_key,),
            ).fetchone()
            if key_row is None:
                return None
            if key_row["payload_hash"] != fingerprint:
                raise APIError(409, "IDEMPOTENCY_CONFLICT", "This request key was already used for a different request.")
            row = connection.execute(
                "SELECT * FROM refund_requests WHERE public_reference=?", (key_row["public_reference"],),
            ).fetchone()
            return self._record(row) if row else None

    def request_for_booking(self, booking_reference: str):
        with self.connect() as connection:
            connection.execute("BEGIN")
            row = connection.execute(
                "SELECT * FROM refund_requests WHERE booking_reference=?"
                " ORDER BY created_at DESC, public_reference DESC LIMIT 1", (booking_reference,),
            ).fetchone()
            return self._record(row) if row else None

    def staff_requests(self) -> list:
        with self.connect() as connection:
            connection.execute("BEGIN")
            rows = connection.execute(
                "SELECT * FROM refund_requests ORDER BY created_at DESC, public_reference DESC"
            ).fetchall()
            return [self._record(row) for row in rows]

    def submit_request(self, *, booking_reference: str, passenger_name: str, email: str, quote: dict,
                       request_key: str, quote_source: str) -> tuple[dict, bool]:
        booking = BOOKINGS.get(booking_reference)
        if booking is None:
            raise APIError(400, "INVALID_INPUT", "This booking is not available for a refund request.")
        fingerprint = submission_fingerprint(booking_reference, email)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            key_row = connection.execute(
                "SELECT payload_hash, public_reference FROM submission_keys WHERE request_key=?", (request_key,),
            ).fetchone()
            if key_row:
                if key_row["payload_hash"] != fingerprint:
                    raise APIError(409, "IDEMPOTENCY_CONFLICT", "This request key was already used for a different request.")
                row = connection.execute(
                    "SELECT * FROM refund_requests WHERE public_reference=?", (key_row["public_reference"],),
                ).fetchone()
                return self._record(row), False
            existing = connection.execute(
                "SELECT * FROM refund_requests WHERE booking_reference=?"
                " ORDER BY created_at DESC, public_reference DESC LIMIT 1", (booking_reference,),
            ).fetchone()
            if existing is not None:
                connection.execute("INSERT OR IGNORE INTO submission_keys VALUES (?, ?, ?)",
                                   (request_key, fingerprint, existing["public_reference"]))
                return self._record(existing), False
            route = decide_route(booking, quote["processStatus"], quote["amount"])
            reference = "AF-" + secrets.token_hex(6).upper()
            created_at = utc_now()
            events = [{"type": "submitted", "at": created_at, "note": ""}]
            connection.execute(
                "INSERT INTO refund_requests ("
                " public_reference, booking_reference, last_name, email, reason, details, created_at,"
                " ticket_value, currency, passenger_name, refund_type, sap_document, amount,"
                " sap_process_status, quote_fetched_at, quote_source, route, request_status, decision_note,"
                " version, events, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (reference, booking_reference, booking["lastName"], email, "flight_disruption", "", created_at,
                 0.0, quote["currency"] or "", passenger_name, "full", quote["sapDocument"], quote["amount"],
                 quote["processStatus"], quote["fetchedAt"], quote_source, route, "pending", "", 1,
                 json.dumps(events, ensure_ascii=False), created_at),
            )
            connection.execute("INSERT INTO submission_keys VALUES (?, ?, ?)", (request_key, fingerprint, reference))
            row = connection.execute(
                "SELECT * FROM refund_requests WHERE public_reference=?", (reference,),
            ).fetchone()
            return self._record(row), True

    def decide(self, reference: str, *, decision: str, note: str, version: int, staff_name: str) -> dict:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM refund_requests WHERE public_reference=?", (reference,),
            ).fetchone()
            if row is None:
                raise APIError(404, "REQUEST_NOT_FOUND", "No refund request matches this reference.")
            current = self._record(row)
            if version != current["version"]:
                raise APIError(409, "VERSION_CONFLICT", "This request changed since you loaded it. Reload and try again.")
            if current["status"] != "pending":
                raise APIError(409, "REQUEST_ALREADY_DECIDED", "This request has already been decided.")
            status = "approved" if decision == "approve" else "declined"
            updated_at = utc_now()
            events = list(current["events"]) + [
                {"type": status, "at": updated_at, "staff": staff_name, "note": note},
            ]
            connection.execute(
                "UPDATE refund_requests SET request_status=?, decision_note=?, version=?, events=?, updated_at=?"
                " WHERE public_reference=?",
                (status, note, current["version"] + 1, json.dumps(events, ensure_ascii=False), updated_at, reference),
            )
            row = connection.execute(
                "SELECT * FROM refund_requests WHERE public_reference=?", (reference,),
            ).fetchone()
            return self._record(row)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


class SAPClient:
    def __init__(self, config: SAPConfig, opener=None):
        self.config = config
        self.opener = opener or build_opener(NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))

    def get_credit_memo(self, identifier) -> dict:
        identifier = text_field(identifier, "SAP document ID", 10)
        if not re.fullmatch(r"[0-9]{1,10}", identifier):
            raise APIError(400, "INVALID_INPUT", "Use a numeric SAP document ID of up to ten digits.")
        if not self.config.configured:
            raise APIError(503, "SAP_UNCONFIGURED", "Configure the personal SAP API key and verified HTTPS service URL on the server.")
        url = self.config.base_url.rstrip("/") + "/CreditMemoRequest/" + identifier
        request = Request(url, headers={"Accept": "application/json", "APIKey": self.config.api_key}, method="GET")
        try:
            with self.opener.open(request, timeout=12) as response:
                encoding = getattr(response, "headers", {}).get("Content-Encoding", "").strip().lower()
                raw = response.read(MAX_SAP_BYTES + 1)
            if len(raw) > MAX_SAP_BYTES:
                raise APIError(502, "SAP_BAD_RESPONSE", "SAP returned a response that exceeds the supported size.")
            if encoding in {"gzip", "x-gzip"}:
                with gzip.GzipFile(fileobj=io.BytesIO(raw), mode="rb") as compressed:
                    raw = compressed.read(MAX_SAP_BYTES + 1)
                if len(raw) > MAX_SAP_BYTES:
                    raise APIError(502, "SAP_BAD_RESPONSE", "SAP returned a response that exceeds the supported size.")
            elif encoding not in {"", "identity"}:
                raise APIError(502, "SAP_BAD_RESPONSE", "SAP returned an unsupported response encoding.")
            payload = json.loads(raw.decode("utf-8"))
        except HTTPError as error:
            errors = {
                401: (401, "SAP_AUTHENTICATION_FAILED", "SAP rejected the personal API authentication. Check server configuration."),
                403: (403, "SAP_FORBIDDEN", "The personal SAP account cannot read this resource."),
                404: (404, "SAP_NOT_FOUND", "No SAP credit memo request matches this document ID."),
                429: (503, "SAP_UNAVAILABLE", "SAP is temporarily limiting requests. Try again later."),
            }
            status, code, message = errors.get(error.code, (503, "SAP_UNAVAILABLE", "SAP is temporarily unavailable. Try again later."))
            error.close()
            raise APIError(status, code, message) from None
        except (TimeoutError,):
            raise APIError(504, "SAP_TIMEOUT", "SAP did not respond in time. Try again.") from None
        except URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise APIError(504, "SAP_TIMEOUT", "SAP did not respond in time. Try again.") from None
            raise APIError(503, "SAP_UNAVAILABLE", "Cannot reach the configured SAP service. Check the connection and retry.") from None
        except (UnicodeDecodeError, json.JSONDecodeError, gzip.BadGzipFile, EOFError, zlib.error):
            raise APIError(502, "SAP_BAD_RESPONSE", "SAP returned an unreadable response.") from None
        label = ("SAP public sandbox · read-only GET" if urlsplit(self.config.base_url).hostname == "sandbox.api.sap.com"
                 else "Personal SAP API · read-only GET")
        return self.normalize(payload, identifier, source_label=label)

    @staticmethod
    def normalize(payload, identifier: str, source_label: str = "SAP API response · read-only GET") -> dict:
        if isinstance(payload, dict) and "d" in payload:
            payload = payload["d"]
        if isinstance(payload, dict) and "value" in payload:
            values = payload["value"]
            if not isinstance(values, list):
                raise APIError(502, "SAP_BAD_RESPONSE", "SAP returned an unexpected document format.")
            payload = next((item for item in values if isinstance(item, dict)
                            and str(item.get("CreditMemoRequest", "")).lstrip("0") == identifier.lstrip("0")), None)
            if payload is None:
                raise APIError(404, "SAP_NOT_FOUND", "No SAP credit memo request matches this document ID.")
        if not isinstance(payload, dict) or str(payload.get("CreditMemoRequest", "")).lstrip("0") != identifier.lstrip("0"):
            raise APIError(502, "SAP_BAD_RESPONSE", "SAP returned an unexpected document format.")
        amount = payload.get("TotalNetAmount")
        try:
            if isinstance(amount, bool):
                raise ValueError
            amount = float(amount) if amount is not None else None
            if amount is not None and not math.isfinite(amount):
                raise ValueError
        except (TypeError, ValueError):
            raise APIError(502, "SAP_BAD_RESPONSE", "SAP returned an invalid financial amount.") from None
        return {
            "id": str(payload["CreditMemoRequest"]), "totalNetAmount": amount,
            "currency": payload.get("TransactionCurrency"),
            "referenceDocument": payload.get("ReferenceSDDocument"),
            "referenceDocumentCategory": payload.get("ReferenceSDDocumentCategory"),
            "processStatusCode": payload.get("OverallSDProcessStatus"),
            "approvalStatusCode": payload.get("SalesDocApprovalStatus", payload.get("CreditMemoReqApprovalStatus")),
            "createdAt": payload.get("CreationDateTime") or payload.get("CreationDate"),
            "source": {"mode": "live", "label": source_label, "fetchedAt": utc_now()},
            "interpretation": "This SAP financial reference does not confirm the paid fare, approval of this application, or refund settlement.",
        }


def make_handler(store: ApplicationStore, sap: SAPClient, *, public_dir: Path = BASE_DIR / "public",
                 auth: AuthConfig | None = None):
    public_dir = public_dir.resolve()
    if auth is None:
        auth, _ = build_auth(deployed=False)

    class Handler(BaseHTTPRequestHandler):
        server_version = "AirAssistPrototype/1.0"
        sys_version = ""

        def log_message(self, format, *args):
            # Request URLs can contain email addresses. Do not log URLs, bodies, tokens or credentials.
            return

        def common_headers(self):
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")

        def json_response(self, status: int, payload: dict):
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.common_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def fail(self, error: APIError):
            self.json_response(error.status, {"error": {"code": error.code, "message": error.message}})

        def json_download(self, record: dict):
            payload = {"format": "airassist-refund-receipt", "generatedAt": utc_now(), "receipt": record}
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")
            filename = "airassist-receipt-" + record["reference"] + ".json"
            self.send_response(200)
            self.common_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="' + filename + '"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def query(self) -> tuple[str, dict]:
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query, keep_blank_values=True)
            if any(len(values) != 1 for values in query.values()):
                raise APIError(400, "INVALID_INPUT", "Provide each query parameter once.")
            return parsed.path, {name: values[0] for name, values in query.items()}

        def validate_local_access(self):
            hosts = self.headers.get_all("Host", [])
            if len(hosts) != 1:
                raise APIError(400, "INVALID_HOST", "Use the local application address.")
            try:
                host = urlsplit("//" + hosts[0])
                allowed_host = (
                    host.hostname in {"127.0.0.1", "localhost"}
                    and host.port == self.server.server_port and not host.username
                    and not host.password and not host.path and not host.query and not host.fragment
                )
            except ValueError:
                allowed_host = False
            if not allowed_host:
                raise APIError(400, "INVALID_HOST", "Use the local application address.")
            origins = self.headers.get_all("Origin", [])
            if not origins:
                return  # Local command-line clients do not send Origin.
            try:
                origin = urlsplit(origins[0])
                allowed_origin = (
                    len(origins) == 1 and origin.scheme == "http"
                    and origin.hostname in {"127.0.0.1", "localhost"}
                    and origin.port == self.server.server_port and not origin.username
                    and not origin.password and not origin.path and not origin.query and not origin.fragment
                )
            except ValueError:
                allowed_origin = False
            if not allowed_origin:
                raise APIError(403, "ORIGIN_NOT_ALLOWED", "Sign in and view requests from the local application page.")

        def bearer_token(self) -> str:
            values = self.headers.get_all("Authorization", [])
            if len(values) != 1:
                raise APIError(401, "UNAUTHENTICATED", "Sign in to continue.")
            value = values[0].strip()
            if not value.startswith("Bearer ") or len(value) > 4096:
                raise APIError(401, "UNAUTHENTICATED", "Sign in to continue.")
            token = value[7:].strip()
            if not token:
                raise APIError(401, "UNAUTHENTICATED", "Sign in to continue.")
            return token

        def require_role(self, role: str) -> dict:
            claims = auth.verify_token(self.bearer_token())
            if claims["role"] != role:
                raise APIError(403, "FORBIDDEN", "This action is not available for this account.")
            return claims

        def rate_limit_client(self) -> str:
            # BaseHTTPRequestHandler exposes the socket peer as the client_address
            # attribute, so the rate-limit helper uses a different name.
            if auth.deployed:
                forwarded = self.headers.get_all("X-Forwarded-For", [])
                if len(forwarded) == 1:
                    first = forwarded[0].split(",", 1)[0].strip()
                    if first and len(first) <= 64:
                        return first
            return self.client_address[0]

        # --- handlers --------------------------------------------------------------------------
        def handle_login(self, payload):
            credentials = validate_login(payload)
            account = auth.authenticate(credentials["username"], credentials["password"], self.rate_limit_client())
            token = auth.issue_token(account, credentials["username"])
            self.json_response(200, {"token": token, "role": account["role"], "displayName": account["displayName"]})

        def handle_me(self):
            claims = self.require_role("passenger")
            account = auth.accounts[claims["subject"]]
            booking = BOOKINGS[account["booking"]]
            quote, quote_error = None, None
            try:
                quote = build_quote(sap.get_credit_memo(booking["sapCreditMemoRequest"]))
            except APIError as error:
                quote_error = {"code": error.code, "message": error.message}
            self.json_response(200, {
                "displayName": account["displayName"], "booking": booking_view(booking),
                "flight": flight_view(booking), "quote": quote, "quoteError": quote_error,
                "request": store.request_for_booking(booking["reference"]),
            })

        def handle_submit(self, payload):
            claims = self.require_role("passenger")
            submission = validate_submission(payload)
            account = auth.accounts[claims["subject"]]
            booking = BOOKINGS[account["booking"]]
            fingerprint = submission_fingerprint(booking["reference"], submission["email"])
            previous = store.find_submission(submission["requestKey"], fingerprint)
            if previous is None:
                previous = store.request_for_booking(booking["reference"])
            if previous is not None:
                self.json_response(200, {
                    "request": previous, "created": False,
                    "message": "This booking already has a refund request. The original request was returned unchanged.",
                })
                return
            record = sap.get_credit_memo(booking["sapCreditMemoRequest"])
            quote = build_quote(record)
            if quote["amount"] is None:
                raise APIError(502, "SAP_QUOTE_INCOMPLETE",
                               "SAP did not return a refund amount for this booking, so a request cannot be created.")
            request_record, created = store.submit_request(
                booking_reference=booking["reference"], passenger_name=booking["passengerName"],
                email=submission["email"], quote=quote, request_key=submission["requestKey"], quote_source="live",
            )
            self.json_response(201 if created else 200, {
                "request": request_record, "created": created,
                "message": ("Full refund request received and awaiting a staff decision." if created
                            else "This booking already has a refund request."),
            })

        def handle_staff_list(self):
            self.require_role("staff")
            self.json_response(200, {"requests": store.staff_requests()})

        def handle_decision(self, reference: str, payload):
            claims = self.require_role("staff")
            if not REFERENCE_PATTERN.fullmatch(reference):
                raise APIError(404, "REQUEST_NOT_FOUND", "No refund request matches this reference.")
            decision = validate_decision(payload)
            account = auth.accounts[claims["subject"]]
            record = store.decide(reference, decision=decision["decision"], note=decision["note"],
                                  version=decision["version"], staff_name=account["displayName"])
            self.json_response(200, {"request": record})

        def handle_receipt(self):
            claims = self.require_role("passenger")
            account = auth.accounts[claims["subject"]]
            record = store.request_for_booking(account["booking"])
            if record is None:
                raise APIError(404, "REQUEST_NOT_FOUND", "No refund request exists for this booking yet.")
            self.json_download(record)

        def do_DELETE(self):
            try:
                self.validate_local_access()
                raise APIError(405, "METHOD_NOT_ALLOWED", "This endpoint does not accept deletions.")
            except APIError as error:
                self.fail(error)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                LOGGER.error("A request could not be completed; sensitive request details were not logged.")
                self.fail(APIError(500, "INTERNAL_ERROR", "The application could not complete this request. Please retry."))

        def do_GET(self):
            try:
                self.validate_local_access()
                path, _ = self.query()
                if path == "/api/health":
                    self.json_response(200, {"status": "ok", "appMode": "prototype", "sap": {
                        "mode": sap.config.mode, "configured": sap.config.configured, "accountPolicy": "personal-only",
                    }, "storage": "sqlite"})
                elif path == "/api/me":
                    self.handle_me()
                elif path == "/api/staff/requests":
                    self.handle_staff_list()
                elif path == "/api/refund-requests/receipt":
                    self.handle_receipt()
                elif path.startswith("/api/"):
                    raise APIError(404, "NOT_FOUND", "This endpoint is not available.")
                else:
                    self.serve_static(path)
            except APIError as error:
                self.fail(error)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                LOGGER.error("A request could not be completed; sensitive request details were not logged.")
                self.fail(APIError(500, "INTERNAL_ERROR", "The application could not complete this request. Please retry."))

        def do_POST(self):
            try:
                self.validate_local_access()
                path, _ = self.query()
                decision_match = DECISION_PATH.fullmatch(path)
                if path not in {"/api/auth/login", "/api/refund-requests"} and decision_match is None:
                    raise APIError(405, "METHOD_NOT_ALLOWED", "This endpoint does not accept submissions.")
                if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise APIError(415, "UNSUPPORTED_MEDIA_TYPE", "Submit this request as JSON.")
                if self.headers.get("Transfer-Encoding"):
                    raise APIError(400, "INVALID_INPUT", "Use a standard JSON request body.")
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    raise APIError(400, "INVALID_INPUT", "Provide a valid request body.") from None
                if length <= 0 or length > MAX_BODY_BYTES:
                    raise APIError(413, "INVALID_INPUT", "The request body is empty or too large.")
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    raise APIError(400, "INVALID_INPUT", "Provide a valid JSON request body.") from None
                if path == "/api/auth/login":
                    self.handle_login(payload)
                elif path == "/api/refund-requests":
                    self.handle_submit(payload)
                else:
                    self.handle_decision(decision_match.group(1).upper(), payload)
            except APIError as error:
                self.fail(error)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                LOGGER.error("A request could not be saved; sensitive request details were not logged.")
                self.fail(APIError(500, "INTERNAL_ERROR", "The application could not save this request. Please retry."))

        def serve_static(self, path: str):
            decoded = unquote(path)
            if "\x00" in decoded:
                raise APIError(404, "NOT_FOUND", "This page is not available.")
            candidate = (public_dir / (decoded.lstrip("/") or "index.html")).resolve()
            if not candidate.is_relative_to(public_dir) or any(part.startswith(".") for part in candidate.relative_to(public_dir).parts) or not candidate.is_file():
                raise APIError(404, "NOT_FOUND", "This page is not available.")
            body = candidate.read_bytes()
            self.send_response(200)
            self.common_headers()
            self.send_header("Content-Type", mimetypes.guess_type(str(candidate))[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def make_server(store: ApplicationStore, sap: SAPClient, *, public_dir: Path = BASE_DIR / "public",
                host: str = "127.0.0.1", port: int = 8789, auth: AuthConfig | None = None) -> ThreadingHTTPServer:
    class Server(ThreadingHTTPServer):
        daemon_threads = True

    return Server((host, port), make_handler(store, sap, public_dir=public_dir, auth=auth))


def main():
    load_personal_env()
    parser = argparse.ArgumentParser(description="Run the local AirAssist A3 prototype.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("AIRASSIST_PORT", "8789")))
    args = parser.parse_args()
    database = Path(os.environ.get("AIRASSIST_DATABASE", str(BASE_DIR / ".data" / "airassist.sqlite3")))
    if not database.is_absolute():
        database = BASE_DIR / database
    config = SAPConfig.from_environment()
    auth, generated = build_auth(deployed=False)
    server = make_server(ApplicationStore(database), SAPClient(config), port=args.port, auth=auth)
    print(f"AirAssist prototype: http://127.0.0.1:{server.server_port}")
    print(f"Personal SAP read-only connection: {'configured' if config.configured else 'unconfigured'}")
    if generated:
        print("Local demo sign-in (passwords generated for this run; set the variables in local config to override):")
        for username, meta in ACCOUNTS.items():
            password = generated.get(meta["passwordEnv"])
            if password:
                print(f"  {username}: {password}")
    else:
        print("Local demo sign-in: account passwords loaded from local config.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
