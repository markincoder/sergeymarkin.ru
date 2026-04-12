# -*- coding: utf-8 -*-
"""Тонкая обёртка для ASGI (gunicorn/uvicorn): `app` из main."""
from main import app

__all__ = ["app"]
