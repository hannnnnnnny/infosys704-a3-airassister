"""Vercel's Python runtime imports this handler without starting a listener."""
from app.cloud_handler import make_cloud_handler

handler = make_cloud_handler()
