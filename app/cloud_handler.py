"""Vercel HTTP adapter; the local server retains its original behavior."""
import mimetypes
import os
from urllib.parse import unquote, urlsplit

try:
    from . import server
    from .cloud_access import new_session, validate_access
    from .cloud_store import CloudStore
except ImportError:
    import server
    from cloud_access import new_session, validate_access
    from cloud_store import CloudStore

ASSETS = {"/": "index.html", **{f"/{name}": name for name in ("index.html", "styles.css", "app.js", "workflow-state.js")}}
COPY_REPLACEMENTS = {
    "local prototype": "course prototype", "Local prototype": "Course prototype",
    "saved locally": "saved in this demo", "stored locally": "stored in this demo",
    "saved local": "saved demo", "local application": "demo application",
    "Local application": "Demo application", "local review": "demo review",
    "local evidence": "demo evidence", "local reviewer": "demo reviewer",
    "local queue": "demo queue", "local events": "demo events",
    "locally and awaiting": "in this demo and awaiting",
}


def cloud_copy(value):
    if isinstance(value, dict):
        return {key: cloud_copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [cloud_copy(item) for item in value]
    if isinstance(value, str):
        for original, replacement in COPY_REPLACEMENTS.items():
            value = value.replace(original, replacement)
    return value


def make_cloud_handler(store=None, sap=None):
    return type("CloudHandler", (CloudHandlerMixin, server.make_handler(
        store if store is not None else CloudStore(),
        sap if sap is not None else server.SAPClient(server.SAPConfig.from_environment()),
    )), {})


class CloudHandlerMixin:
    def validate_local_access(self):
        validate_access(self.headers, urlsplit(self.path).path)

    def common_headers(self):
        super().common_headers()
        if urlsplit(self.path).path in {"/", "/index.html"} and os.environ.get("BLOB_READ_WRITE_TOKEN"):
            self.send_header("Set-Cookie", new_session())

    def json_response(self, status, payload):
        payload = dict(payload)
        if "message" in payload:
            payload["message"] = cloud_copy(payload["message"])
        if payload.get("status") == "ok" and "storage" in payload:
            payload.update(appMode="cloud-demo", storage="private-blob-sqlite-snapshot")
        super().json_response(status, payload)

    def serve_static(self, path):
        name = ASSETS.get(unquote(path))
        if name is None:
            raise server.APIError(404, "NOT_FOUND", "This page is not available.")
        content = (server.BASE_DIR / "public" / name).read_text(encoding="utf-8")
        if name in {"index.html", "app.js"}:
            content = cloud_copy(content)
        if name == "index.html":
            content = content.replace("Sample bookings. Requests stored locally.",
                "Sample bookings. Use an example email; no real traveller details.")
            content = content.replace("Sample bookings. Requests stored in this demo.",
                "Sample bookings. Use an example email; no real traveller details.")
        body = content.encode()
        self.send_response(200)
        self.common_headers()
        self.send_header("Content-Type", (mimetypes.guess_type(name)[0] or "text/plain") + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
