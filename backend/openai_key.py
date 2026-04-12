# -*- coding: utf-8 -*-
"""OPENAI_API_KEY из окружения (Docker env_file, .env через config.load_dotenv)."""
from __future__ import annotations

import os


def openai_api_key() -> str:
    return (os.environ.get("OPENAI_API_KEY") or "").strip()
