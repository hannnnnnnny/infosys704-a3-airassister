"""AirAssist course prototype: local applications and read-only personal SAP access.

Run with Python 3.10+: python server.py
Only public/ is served. The SQLite database and personal .env stay server-side.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
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
REASONS = {"flight_cancelled", "schedule_changed", "other"}
SAP_HOSTS = {"api.sap.com", "sandbox.api.sap.com"}
PERSONAL_ENV_KEYS = {
    "AIRASSIST_SAP_MODE", "AIRASSIST_SAP_BASE_URL", "AIRASSIST_SAP_API_KEY",
    "AIRASSIST_SAP_ACCOUNT_TYPE", "AIRASSIST_DATABASE", "AIRASSIST_PORT",
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


BOOKINGS = {
    reference: {
        "reference": reference, "lastName": "Taylor", "traveller": "Alex Taylor",
        "flight": "NZ423", "fromCode": "AKL", "fromCity": "Auckland",
        "toCode": "WLG", "toCity": "Wellington", "date": "2026-10-15",
        "departure": "10:30 AM", "arrival": "11:40 AM", "currency": "NZD",
        "ticketValue": 248.0, "channel": channel, "flightStatus": "cancelled",
        "source": {"mode": "synthetic", "label": "Sample journey"},
    }
    for reference, channel in [("NZ7K2H", "direct"), ("NZ8T3H", "agent")]
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


def lookup_booking(reference, last_name) -> dict:
    reference = text_field(reference, "booking reference", 6).upper()
    last_name = text_field(last_name, "last name", 80)
    if not re.fullmatch(r"[A-Z0-9]{6}", reference):
        raise APIError(400, "INVALID_INPUT", "Use the six-character booking reference.")
    booking = BOOKINGS.get(reference)
    if not booking or booking["lastName"].casefold() != last_name.casefold():
        raise APIError(404, "BOOKING_NOT_FOUND", "No sample booking matches these details.")
    return dict(booking)


def validate_application(payload) -> dict:
    if not isinstance(payload, dict):
        raise APIError(400, "INVALID_INPUT", "Provide a JSON object for the application.")
    booking = lookup_booking(payload.get("bookingReference"), payload.get("lastName"))
    if booking["channel"] != "direct":
        raise APIError(403, "BOOKING_NOT_ELIGIBLE", "For this agent-booked sample, contact the travel agent.")
    email = normalized_email(payload.get("email"))
    reason = text_field(payload.get("reason"), "reason", 40)
    if reason not in REASONS:
        raise APIError(400, "INVALID_INPUT", "Choose flight cancelled, schedule changed, or other reason.")
    details = text_field(payload.get("details", ""), "additional details", 2000, required=False)
    if payload.get("acknowledged") is not True:
        raise APIError(400, "ACKNOWLEDGEMENT_REQUIRED", "Acknowledge that the application requires review.")
    request_key = text_field(payload.get("requestKey"), "request key", 36)
    try:
        request_key = str(uuid.UUID(request_key))
    except ValueError:
        raise APIError(400, "INVALID_INPUT", "Provide a valid request key.") from None
    return {
        "bookingReference": booking["reference"], "lastName": booking["lastName"],
        "email": email, "reason": reason, "details": details, "requestKey": request_key,
        "ticketValue": booking["ticketValue"], "currency": booking["currency"],
    }


MANUAL_CHECK_NOTE = "Local prototype review note only; it does not verify real airline payment or refund policy."


def supporting_required(reason: str, details: str) -> bool:
    return reason == "other" or bool((details or "").strip())


def review_missing_items(reason: str, details: str, checks: dict) -> list:
    missing = []
    if not checks["paymentEvidenceReviewed"]:
        missing.append("Payment evidence review")
    if not checks["refundRulesReviewed"]:
        missing.append("Refund rules review")
    if supporting_required(reason, details) and not checks["supportingDetailsReviewed"]:
        missing.append("Supporting details review")
    return missing


def case_checklist(reason: str, details: str, checks: dict) -> list:
    required_supporting = supporting_required(reason, details)
    return [
        {"id": "booking", "label": "Booking details", "status": "available", "source": "Sample booking", "required": True},
        {"id": "contact", "label": "Contact details", "status": "available", "source": "Local application", "required": True},
        {"id": "payment", "label": "Payment evidence review", "status": "recorded" if checks["paymentEvidenceReviewed"] else "missing",
         "source": "Manual prototype check", "required": True, "detail": MANUAL_CHECK_NOTE},
        {"id": "rules", "label": "Refund rules review", "status": "recorded" if checks["refundRulesReviewed"] else "missing",
         "source": "Manual prototype check", "required": True, "detail": MANUAL_CHECK_NOTE},
        {"id": "supporting", "label": "Supporting details review",
         "status": "recorded" if checks["supportingDetailsReviewed"] else ("missing" if required_supporting else "not_required"),
         "source": "Manual prototype check", "required": required_supporting, "detail": MANUAL_CHECK_NOTE},
    ]


def case_triage(reason: str, details: str, checks: dict, specialist_required: bool) -> dict:
    missing = review_missing_items(reason, details, checks)
    if missing:
        return {
            "route": "information_needed", "label": "Information needed", "queue": "Information follow-up",
            "ownerRole": "Case coordinator", "readyForHandoff": False, "ruleVersion": "prototype-v1",
            "reasons": [f"Missing required review item: {item}." for item in missing],
        }
    if reason == "other" or specialist_required:
        reasons = []
        if reason == "other":
            reasons.append('The application reason is "other", so a specialist review is required.')
        if specialist_required:
            reasons.append("A manual specialist review flag was set.")
        return {
            "route": "complex", "label": "Complex review", "queue": "Specialist review",
            "ownerRole": "Refund specialist", "readyForHandoff": True, "ruleVersion": "prototype-v1",
            "reasons": reasons,
        }
    return {
        "route": "standard", "label": "Standard review", "queue": "Standard review",
        "ownerRole": "Refund reviewer", "readyForHandoff": True, "ruleVersion": "prototype-v1",
        "reasons": ["All required checks are recorded and no exception flag is set."],
    }


def validate_review_payload(payload) -> dict:
    if not isinstance(payload, dict):
        raise APIError(400, "INVALID_INPUT", "Provide a JSON object for the review.")
    reference = text_field(payload.get("reference"), "request reference", 40)
    email = normalized_email(payload.get("email"))
    version = payload.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        raise APIError(400, "INVALID_INPUT", "Provide the current review version as an integer.")
    checks = payload.get("checks")
    if (not isinstance(checks, dict)
            or set(checks) != {"paymentEvidenceReviewed", "refundRulesReviewed", "supportingDetailsReviewed"}
            or not all(isinstance(checks[key], bool) for key in checks)):
        raise APIError(400, "INVALID_INPUT", "Provide the exact three review check fields as booleans.")
    payment_reference = payload.get("paymentReference")
    if (not isinstance(payment_reference, str) or len(payment_reference.strip()) > 80
            or any(ord(char) < 32 for char in payment_reference)):
        raise APIError(400, "INVALID_INPUT", "Provide a payment reference of up to 80 characters.")
    specialist_required = payload.get("specialistRequired")
    if not isinstance(specialist_required, bool):
        raise APIError(400, "INVALID_INPUT", "Provide specialistRequired as a boolean.")
    note = payload.get("note")
    if (not isinstance(note, str) or not note.strip() or len(note) > 1000
            or any(ord(char) < 32 and char not in "\n\t" for char in note)):
        raise APIError(400, "INVALID_INPUT", "Provide a review note of up to 1000 characters.")
    action = payload.get("action")
    if not isinstance(action, str) or action not in {"save_review", "handoff", "reopen"}:
        raise APIError(400, "INVALID_INPUT", "Choose save_review, handoff, or reopen.")
    if checks["paymentEvidenceReviewed"] and not payment_reference.strip():
        raise APIError(400, "INVALID_INPUT", "Provide a payment reference when payment evidence is marked reviewed.")
    return {
        "reference": reference, "email": email, "version": version, "checks": dict(checks),
        "paymentReference": payment_reference.strip(), "specialistRequired": specialist_required,
        "note": note.strip(), "action": action,
    }


def validate_financial_reference_payload(payload) -> dict:
    if not isinstance(payload, dict):
        raise APIError(400, "INVALID_INPUT", "Provide a JSON object for the financial reference.")
    version = payload.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        raise APIError(400, "INVALID_INPUT", "Provide the current review version as an integer.")
    identifier = text_field(payload.get("documentId"), "SAP document ID", 10)
    if not re.fullmatch(r"[0-9]{1,10}", identifier):
        raise APIError(400, "INVALID_INPUT", "Use a numeric SAP document ID of up to ten digits.")
    return {
        "reference": text_field(payload.get("reference"), "request reference", 40).upper(),
        "email": normalized_email(payload.get("email")), "version": version,
        "documentId": identifier, "note": text_field(payload.get("note"), "reference note", 1000),
    }


def documentary_financial_reference(record: dict, request_input: dict, version: int, captured_at: str) -> dict:
    """Copy only documentary fields; this does not establish any booking link."""
    if not isinstance(record, dict) or not isinstance(record.get("id"), str):
        raise APIError(502, "SAP_BAD_RESPONSE", "SAP returned an unexpected document format.")
    identifier = record["id"]
    if not re.fullmatch(r"[0-9]{1,10}", identifier) or identifier.lstrip("0") != request_input["documentId"].lstrip("0"):
        raise APIError(502, "SAP_BAD_RESPONSE", "SAP returned an unexpected document format.")
    amount = record.get("totalNetAmount")
    if amount is not None and (isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount)):
        raise APIError(502, "SAP_BAD_RESPONSE", "SAP returned an invalid financial amount.")
    safe_record = {"id": identifier, "totalNetAmount": amount}
    for field in ("currency", "referenceDocument", "referenceDocumentCategory", "processStatusCode", "approvalStatusCode", "createdAt"):
        value = record.get(field)
        if value is not None and (not isinstance(value, str) or len(value) > 120 or any(ord(char) < 32 for char in value)):
            raise APIError(502, "SAP_BAD_RESPONSE", "SAP returned an unexpected document format.")
        safe_record[field] = value
    provenance = record.get("source")
    if not isinstance(provenance, dict) or provenance.get("mode") != "live" or any(
        not isinstance(provenance.get(field), str) or not provenance[field] or len(provenance[field]) > 200
        or any(ord(char) < 32 for char in provenance[field]) for field in ("label", "fetchedAt")
    ):
        raise APIError(502, "SAP_BAD_RESPONSE", "SAP returned an unexpected source format.")
    return {
        "documentId": identifier, "record": safe_record,
        "source": {field: provenance[field] for field in ("mode", "label", "fetchedAt")},
        "capturedAt": captured_at, "note": request_input["note"], "version": version,
        "context": "demonstration_only", "bookingMatch": "not_verified",
        "paymentVerification": "not_performed", "refundEligibility": "not_assessed",
        "interpretation": "Demonstration-only financial reference. Not matched to this booking; does not verify payment, refund eligibility, approval or settlement.",
    }


class ApplicationStore:
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
                CREATE TABLE IF NOT EXISTS review_state (
                    public_reference TEXT PRIMARY KEY REFERENCES refund_requests(public_reference),
                    review_state TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    check_payment INTEGER NOT NULL,
                    check_rules INTEGER NOT NULL,
                    check_supporting INTEGER NOT NULL,
                    payment_reference TEXT NOT NULL,
                    specialist_required INTEGER NOT NULL,
                    review_note TEXT NOT NULL,
                    events TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS review_financial_references (
                    public_reference TEXT NOT NULL REFERENCES refund_requests(public_reference),
                    version INTEGER NOT NULL,
                    captured_record TEXT NOT NULL,
                    PRIMARY KEY(public_reference, version)
                );
            """)

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

    @staticmethod
    def _default_events(created_at: str) -> list:
        return [{
            "type": "submitted", "at": created_at, "summary": "Application received locally and awaiting review.",
            "note": "", "route": "", "queue": "", "version": 0,
        }]

    @staticmethod
    def _financial_reference(connection, reference: str):
        row = connection.execute(
            "SELECT captured_record FROM review_financial_references WHERE public_reference=? ORDER BY version DESC LIMIT 1",
            (reference,),
        ).fetchone()
        return json.loads(row["captured_record"]) if row else None

    def _review_snapshot(self, row: sqlite3.Row, review_row, financial_reference=None) -> dict:
        if review_row is None:
            return {
                "state": "not_started", "version": 0,
                "checks": {"paymentEvidenceReviewed": False, "refundRulesReviewed": False, "supportingDetailsReviewed": False},
                "paymentReference": "", "specialistRequired": False, "reviewNote": "",
                "events": self._default_events(row["created_at"]), "updatedAt": row["created_at"],
                "financialReference": financial_reference,
            }
        return {
            "state": review_row["review_state"], "version": review_row["version"],
            "checks": {
                "paymentEvidenceReviewed": bool(review_row["check_payment"]),
                "refundRulesReviewed": bool(review_row["check_rules"]),
                "supportingDetailsReviewed": bool(review_row["check_supporting"]),
            },
            "paymentReference": review_row["payment_reference"],
            "specialistRequired": bool(review_row["specialist_required"]),
            "reviewNote": review_row["review_note"],
            "events": json.loads(review_row["events"]),
            "updatedAt": review_row["updated_at"], "financialReference": financial_reference,
        }

    def _request_record(self, row: sqlite3.Row, snapshot: dict) -> dict:
        missing = review_missing_items(row["reason"], row["details"], snapshot["checks"])
        triage = case_triage(row["reason"], row["details"], snapshot["checks"], snapshot["specialistRequired"])
        if snapshot["state"] == "queued":
            status, status_label = "queued_for_review", "Queued · local review"
        elif snapshot["state"] == "prepared" and missing:
            status, status_label = "information_needed", "Information needed · local review"
        elif snapshot["state"] == "prepared":
            status, status_label = "review_prepared", "Prepared · local review"
        else:
            status, status_label = "submitted", "Received · awaiting review"
        return {
            "publicReference": row["public_reference"], "bookingReference": row["booking_reference"],
            "lastName": row["last_name"], "email": row["email"], "reason": row["reason"],
            "details": row["details"], "status": status, "statusLabel": status_label,
            "createdAt": row["created_at"], "updatedAt": snapshot["updatedAt"],
            "sapCreditMemoRequestId": None, "ticketValue": row["ticket_value"], "currency": row["currency"],
            "source": {"mode": "local", "label": "Local prototype application"},
            "review": {
                "state": snapshot["state"], "version": snapshot["version"],
                "route": triage["route"], "routeLabel": triage["label"], "queue": triage["queue"],
                "ownerRole": triage["ownerRole"], "missingItems": missing, "events": snapshot["events"],
                "financialReference": snapshot["financialReference"],
            },
        }

    def _case_bundle(self, row: sqlite3.Row, snapshot: dict) -> dict:
        request = self._request_record(row, snapshot)
        return {
            "request": request, "booking": dict(BOOKINGS[row["booking_reference"]]),
            "version": snapshot["version"], "checks": dict(snapshot["checks"]),
            "paymentReference": snapshot["paymentReference"], "specialistRequired": snapshot["specialistRequired"],
            "reviewNote": snapshot["reviewNote"], "reviewState": snapshot["state"],
            "checklist": case_checklist(row["reason"], row["details"], snapshot["checks"]),
            "triage": case_triage(row["reason"], row["details"], snapshot["checks"], snapshot["specialistRequired"]),
            "events": snapshot["events"], "financialReference": snapshot["financialReference"],
        }

    def submit(self, application: dict) -> tuple[dict, bool]:
        fingerprint = hashlib.sha256(json.dumps(
            {key: value for key, value in application.items() if key != "requestKey"},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")).hexdigest()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            key_row = connection.execute(
                "SELECT payload_hash, public_reference FROM submission_keys WHERE request_key=?",
                (application["requestKey"],),
            ).fetchone()
            if key_row:
                if key_row["payload_hash"] != fingerprint:
                    raise APIError(409, "IDEMPOTENCY_CONFLICT", "This submission key has already been used for different details.")
                row = connection.execute(
                    "SELECT * FROM refund_requests WHERE public_reference=?", (key_row["public_reference"],),
                ).fetchone()
                review_row = connection.execute(
                    "SELECT * FROM review_state WHERE public_reference=?", (row["public_reference"],),
                ).fetchone()
                snapshot = self._review_snapshot(row, review_row, self._financial_reference(connection, row["public_reference"]))
                return self._request_record(row, snapshot), False
            row = connection.execute(
                "SELECT * FROM refund_requests WHERE booking_reference=? AND email=?",
                (application["bookingReference"], application["email"]),
            ).fetchone()
            created = row is None
            if created:
                reference, created_at = "AF-" + secrets.token_hex(6).upper(), utc_now()
                connection.execute(
                    "INSERT INTO refund_requests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (reference, application["bookingReference"], application["lastName"], application["email"],
                     application["reason"], application["details"], created_at, application["ticketValue"], application["currency"]),
                )
                row = connection.execute("SELECT * FROM refund_requests WHERE public_reference=?", (reference,)).fetchone()
            connection.execute("INSERT INTO submission_keys VALUES (?, ?, ?)",
                               (application["requestKey"], fingerprint, row["public_reference"]))
            review_row = connection.execute(
                "SELECT * FROM review_state WHERE public_reference=?", (row["public_reference"],),
            ).fetchone()
            snapshot = self._review_snapshot(row, review_row, self._financial_reference(connection, row["public_reference"]))
            return self._request_record(row, snapshot), created

    def find(self, reference, email) -> dict:
        reference = text_field(reference, "request reference", 40).upper()
        email = normalized_email(email)
        with self.connect() as connection:
            connection.execute("BEGIN")
            row = connection.execute(
                "SELECT * FROM refund_requests WHERE public_reference=? AND email=?", (reference, email),
            ).fetchone()
            if row is None:
                raise APIError(404, "REQUEST_NOT_FOUND", "No application matches these details.")
            review_row = connection.execute(
                "SELECT * FROM review_state WHERE public_reference=?", (row["public_reference"],),
            ).fetchone()
            snapshot = self._review_snapshot(row, review_row, self._financial_reference(connection, row["public_reference"]))
        return self._request_record(row, snapshot)

    def get_case(self, reference, email) -> dict:
        reference = text_field(reference, "request reference", 40).upper()
        email = normalized_email(email)
        with self.connect() as connection:
            connection.execute("BEGIN")
            row = connection.execute(
                "SELECT * FROM refund_requests WHERE public_reference=? AND email=?", (reference, email),
            ).fetchone()
            if row is None:
                raise APIError(404, "REQUEST_NOT_FOUND", "No application matches these details.")
            review_row = connection.execute(
                "SELECT * FROM review_state WHERE public_reference=?", (row["public_reference"],),
            ).fetchone()
            snapshot = self._review_snapshot(row, review_row, self._financial_reference(connection, row["public_reference"]))
            return self._case_bundle(row, snapshot)

    def update_review(self, review_input: dict) -> dict:
        reference = text_field(review_input["reference"], "request reference", 40).upper()
        email = normalized_email(review_input["email"])
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM refund_requests WHERE public_reference=? AND email=?", (reference, email),
            ).fetchone()
            if row is None:
                raise APIError(404, "REQUEST_NOT_FOUND", "No application matches these details.")
            review_row = connection.execute(
                "SELECT * FROM review_state WHERE public_reference=?", (row["public_reference"],),
            ).fetchone()
            current = self._review_snapshot(row, review_row, self._financial_reference(connection, row["public_reference"]))
            if current["version"] != review_input["version"]:
                raise APIError(409, "REVIEW_VERSION_CONFLICT", "This review changed elsewhere. Reload the case and retry.")
            action = review_input["action"]
            if action in {"save_review", "handoff"} and current["state"] == "queued":
                raise APIError(409, "CASE_ALREADY_QUEUED", "This case is already queued for review.")
            if action in {"save_review", "handoff"} and current["state"] not in {"not_started", "prepared"}:
                raise APIError(409, "INVALID_REVIEW_STATE", "This case cannot be reviewed from its current state.")
            if action == "reopen" and current["state"] != "queued":
                raise APIError(409, "INVALID_REVIEW_STATE", "Only a queued case can be reopened.")
            checks = dict(review_input["checks"])
            missing = review_missing_items(row["reason"], row["details"], checks)
            if action == "handoff" and missing:
                raise APIError(409, "INCOMPLETE_CASE", "Record every required review item before handoff.")
            state = {"save_review": "prepared", "handoff": "queued", "reopen": "prepared"}[action]
            triage = case_triage(row["reason"], row["details"], checks, review_input["specialistRequired"])
            updated_at = utc_now()
            event_type = {"save_review": "review_saved", "handoff": "handoff", "reopen": "reopened"}[action]
            summary = {
                "save_review": "Local review details saved.",
                "handoff": "Case handed off for local review.",
                "reopen": "Case reopened for local review.",
            }[action]
            events = list(current["events"]) + [{
                "type": event_type, "at": updated_at, "summary": summary, "note": review_input["note"],
                "route": triage["route"], "queue": triage["queue"], "version": current["version"] + 1,
            }]
            if review_row is None:
                connection.execute(
                    "INSERT INTO review_state VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (row["public_reference"], state, current["version"] + 1, int(checks["paymentEvidenceReviewed"]),
                     int(checks["refundRulesReviewed"]), int(checks["supportingDetailsReviewed"]),
                     review_input["paymentReference"], int(review_input["specialistRequired"]),
                     review_input["note"], json.dumps(events, ensure_ascii=False), updated_at),
                )
            else:
                connection.execute(
                    "UPDATE review_state SET review_state=?, version=?, check_payment=?, check_rules=?, check_supporting=?,"
                    " payment_reference=?, specialist_required=?, review_note=?, events=?, updated_at=? WHERE public_reference=?",
                    (state, current["version"] + 1, int(checks["paymentEvidenceReviewed"]),
                     int(checks["refundRulesReviewed"]), int(checks["supportingDetailsReviewed"]),
                     review_input["paymentReference"], int(review_input["specialistRequired"]),
                     review_input["note"], json.dumps(events, ensure_ascii=False), updated_at, row["public_reference"]),
                )
            snapshot = {
                "state": state, "version": current["version"] + 1, "checks": checks,
                "paymentReference": review_input["paymentReference"],
                "specialistRequired": review_input["specialistRequired"],
                "reviewNote": review_input["note"], "events": events, "updatedAt": updated_at,
                "financialReference": current["financialReference"],
            }
            return self._case_bundle(row, snapshot)

    @staticmethod
    def _capture_guard(current_version: int, state: str, requested_version: int):
        if current_version != requested_version:
            raise APIError(409, "REVIEW_VERSION_CONFLICT", "This review changed elsewhere. Reload the case and retry.")
        if state == "queued":
            raise APIError(409, "CASE_ALREADY_QUEUED", "Reopen the local case before capturing a financial reference.")
        if state not in {"not_started", "prepared"}:
            raise APIError(409, "INVALID_REVIEW_STATE", "This case cannot capture a reference from its current state.")

    def precheck_financial_reference(self, request_input: dict):
        case = self.get_case(request_input["reference"], request_input["email"])
        self._capture_guard(case["version"], case["reviewState"], request_input["version"])

    def capture_financial_reference(self, request_input: dict, record: dict) -> dict:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM refund_requests WHERE public_reference=? AND email=?",
                (request_input["reference"], request_input["email"]),
            ).fetchone()
            if row is None:
                raise APIError(404, "REQUEST_NOT_FOUND", "No application matches these details.")
            review_row = connection.execute(
                "SELECT * FROM review_state WHERE public_reference=?", (row["public_reference"],),
            ).fetchone()
            current = self._review_snapshot(row, review_row, self._financial_reference(connection, row["public_reference"]))
            self._capture_guard(current["version"], current["state"], request_input["version"])
            captured_at = utc_now()
            version = current["version"] + 1
            reference = documentary_financial_reference(record, request_input, version, captured_at)
            triage = case_triage(row["reason"], row["details"], current["checks"], current["specialistRequired"])
            events = list(current["events"]) + [{
                "type": "financial_reference_captured", "at": captured_at,
                "summary": "SAP financial reference captured for demonstration; booking and payment remain unverified.",
                "note": request_input["note"], "route": triage["route"], "queue": triage["queue"], "version": version,
            }]
            connection.execute("INSERT INTO review_financial_references VALUES (?, ?, ?)",
                               (row["public_reference"], version, json.dumps(reference, ensure_ascii=False, allow_nan=False)))
            if review_row is None:
                connection.execute("INSERT INTO review_state VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
                    row["public_reference"], current["state"], version,
                    int(current["checks"]["paymentEvidenceReviewed"]), int(current["checks"]["refundRulesReviewed"]),
                    int(current["checks"]["supportingDetailsReviewed"]), current["paymentReference"],
                    int(current["specialistRequired"]), current["reviewNote"], json.dumps(events, ensure_ascii=False), captured_at,
                ))
            else:
                connection.execute("UPDATE review_state SET version=?, events=?, updated_at=? WHERE public_reference=?",
                                   (version, json.dumps(events, ensure_ascii=False), captured_at, row["public_reference"]))
            snapshot = dict(current, version=version, events=events, updatedAt=captured_at, financialReference=reference)
            return self._case_bundle(row, snapshot)


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


def make_server(store: ApplicationStore, sap: SAPClient, *, public_dir: Path = BASE_DIR / "public",
                host: str = "127.0.0.1", port: int = 8789) -> ThreadingHTTPServer:
    public_dir = public_dir.resolve()

    class Handler(BaseHTTPRequestHandler):
        server_version = "AirAssistPrototype/1.0"
        sys_version = ""

        def log_message(self, format, *args):
            # Request URLs can contain email addresses. Do not log URLs, bodies, or credentials.
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
            payload = {"format": "airassist-application-receipt", "generatedAt": utc_now(), "receipt": record}
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")
            filename = "airassist-receipt-" + record["publicReference"] + ".json"
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
                raise APIError(403, "ORIGIN_NOT_ALLOWED", "Submit or view applications from the local application page.")

        def do_GET(self):
            try:
                self.validate_local_access()
                path, query = self.query()
                if path == "/api/health":
                    self.json_response(200, {"status": "ok", "appMode": "prototype", "sap": {
                        "mode": sap.config.mode, "configured": sap.config.configured, "accountPolicy": "personal-only",
                    }, "storage": "sqlite"})
                elif path == "/api/bookings":
                    self.json_response(200, {"booking": lookup_booking(query.get("reference"), query.get("lastname"))})
                elif path == "/api/refund-requests":
                    self.json_response(200, {"request": store.find(query.get("reference"), query.get("email"))})
                elif path == "/api/review-cases":
                    self.json_response(200, {"case": store.get_case(query.get("reference"), query.get("email"))})
                elif path == "/api/refund-requests/receipt":
                    record = store.find(query.get("reference"), query.get("email"))
                    self.json_download(record)
                elif path == "/api/sap/credit-memo-requests":
                    self.json_response(200, {"record": sap.get_credit_memo(query.get("id"))})
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
                path, query = self.query()
                if path not in {"/api/refund-requests", "/api/review-cases", "/api/review-cases/financial-reference"}:
                    raise APIError(405, "METHOD_NOT_ALLOWED", "Only local refund applications can be submitted.")
                if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise APIError(415, "UNSUPPORTED_MEDIA_TYPE", "Submit the application as JSON.")
                if self.headers.get("Transfer-Encoding"):
                    raise APIError(400, "INVALID_INPUT", "Use a standard JSON request body.")
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    raise APIError(400, "INVALID_INPUT", "Provide a valid request body.") from None
                if length <= 0 or length > MAX_BODY_BYTES:
                    raise APIError(413, "INVALID_INPUT", "The application body is empty or too large.")
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    raise APIError(400, "INVALID_INPUT", "Provide a valid JSON request body.") from None
                if path == "/api/refund-requests":
                    application = validate_application(payload)
                    record, created = store.submit(application)
                    message = (
                        "Application saved locally and awaiting review. No SAP document was created."
                        if created else
                        "An application for this booking and email already exists. Your original application was returned unchanged."
                    )
                    self.json_response(201 if created else 200, {"request": record, "created": created, "message": message})
                elif path == "/api/review-cases":
                    review_input = validate_review_payload(payload)
                    bundle = store.update_review(review_input)
                    self.json_response(200, {"case": bundle})
                else:
                    request_input = validate_financial_reference_payload(payload)
                    store.precheck_financial_reference(request_input)
                    record = sap.get_credit_memo(request_input["documentId"])
                    bundle = store.capture_financial_reference(request_input, record)
                    self.json_response(200, {"case": bundle})
            except APIError as error:
                self.fail(error)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                LOGGER.error("An application could not be saved; sensitive request details were not logged.")
                self.fail(APIError(500, "INTERNAL_ERROR", "The application could not be saved. Please retry."))

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

    class Server(ThreadingHTTPServer):
        daemon_threads = True

    return Server((host, port), Handler)


def main():
    load_personal_env()
    parser = argparse.ArgumentParser(description="Run the local AirAssist A3 prototype.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("AIRASSIST_PORT", "8789")))
    args = parser.parse_args()
    database = Path(os.environ.get("AIRASSIST_DATABASE", str(BASE_DIR / ".data" / "airassist.sqlite3")))
    if not database.is_absolute():
        database = BASE_DIR / database
    config = SAPConfig.from_environment()
    server = make_server(ApplicationStore(database), SAPClient(config), port=args.port)
    print(f"AirAssist prototype: http://127.0.0.1:{server.server_port}")
    print(f"Personal SAP read-only connection: {'configured' if config.configured else 'unconfigured'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
