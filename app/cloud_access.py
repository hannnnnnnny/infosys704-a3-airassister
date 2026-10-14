"""Exact-origin checks and signed, anonymous sessions for the public demo."""
import hashlib
import hmac
import os
import re
import secrets
import time
from http.cookies import CookieError, SimpleCookie

try:
    from .server import APIError
except ImportError:
    from server import APIError

COOKIE_NAME = "airassist_session"
SESSION_SECONDS = 86_400


def session_secret():
    secret = os.environ.get("BLOB_READ_WRITE_TOKEN", "")
    if not secret:
        raise APIError(503, "SESSION_UNAVAILABLE", "Demo sessions are unavailable. Please retry shortly.")
    return secret.encode()


def sign(value):
    return hmac.new(session_secret(), ("airassist-session:" + value).encode(), hashlib.sha256).hexdigest()


def new_session():
    value = f"{int(time.time())}.{secrets.token_hex(16)}"
    return f"{COOKIE_NAME}={value}.{sign(value)}; Path=/; Max-Age={SESSION_SECONDS}; HttpOnly; Secure; SameSite=Strict"


def valid_session(cookie):
    if not cookie or len(cookie) > 8192:
        return False
    try:
        cookies = SimpleCookie(cookie)
        morsel = cookies.get(COOKIE_NAME)
        if morsel is None:
            return False
        timestamp, nonce, signature = morsel.value.split(".")
        if not re.fullmatch(r"[0-9]{10}\.[a-f0-9]{32}\.[a-f0-9]{64}", morsel.value):
            return False
        age = time.time() - int(timestamp)
        return 0 <= age < SESSION_SECONDS and hmac.compare_digest(signature, sign(timestamp + "." + nonce))
    except (CookieError, ValueError):
        return False


def allowed_hosts():
    values = [os.environ.get(key, "") for key in ("VERCEL_URL", "VERCEL_BRANCH_URL", "VERCEL_PROJECT_PRODUCTION_URL")]
    values += os.environ.get("AIRASSIST_ALLOWED_HOSTS", "").split(",")
    return {value.strip().lower() for value in values if re.fullmatch(r"[a-zA-Z0-9.-]+", value.strip())}


def validate_access(headers, path):
    hosts = headers.get_all("Host", [])
    if len(hosts) != 1 or hosts[0].lower() not in allowed_hosts():
        raise APIError(400, "INVALID_HOST", "Use the deployed demo address.")
    origins = headers.get_all("Origin", [])
    if origins and (len(origins) != 1 or origins[0] != "https://" + hosts[0].lower()):
        raise APIError(403, "ORIGIN_NOT_ALLOWED", "Use the deployed demo page.")
    if path.startswith("/api/") and path != "/api/health" and not valid_session(headers.get("Cookie")):
        raise APIError(401, "SESSION_REQUIRED", "Open or refresh the demo page before using this service.")
