"""Vercel's Python runtime imports this handler without starting a listener."""
from app.cloud_handler import make_cloud_handler
from http.server import BaseHTTPRequestHandler


class handler(make_cloud_handler(), BaseHTTPRequestHandler):
    """The explicit base lets Vercel's build-time AST discovery identify HTTP."""
