# -*- coding: utf-8 -*-
"""Конфигурация приложения (FastAPI)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
# utf-8-sig: BOM из Windows не ломает имя переменной OPENAI_API_KEY
load_dotenv(BASE_DIR / ".env", encoding="utf-8-sig")

from backend.openai_key import openai_api_key  # noqa: E402

# FAQ/RAG: не в database/ — том Docker монтируется на database/, иначе перекрыл бы RAG из образа
RAG_DATA_DIR = BASE_DIR / "backend" / "rag_data"


class Config:
    """Базовые настройки."""

    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-change-me-in-production"
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or (
        "sqlite:///" + str(BASE_DIR / "database" / "app.db")
    )

    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")

    LOG_LEVEL = os.environ.get("LOG_LEVEL") or "INFO"

    SITE_URL = os.environ.get("SITE_URL") or "https://sergeymarkin.ru"
    SEO_OG_IMAGE = os.environ.get("SEO_OG_IMAGE") or "/static/images/hero-profile.svg"

    CHAT_API_BASE = (os.environ.get("CHAT_API_BASE") or "").strip().rstrip("/")
    OPENAI_API_KEY = (os.environ.get("OPENAI_API_KEY") or "").strip()  # см. openai_api_key()

    MAIL_SERVER = os.environ.get("MAIL_SERVER") or "smtp.yandex.ru"
    MAIL_PORT = int(os.environ.get("MAIL_PORT") or "465")
    MAIL_USE_SSL = os.environ.get("MAIL_USE_SSL", "true").lower() in ("1", "true", "yes")
    MAIL_USERNAME = (os.environ.get("MAIL_USERNAME") or "").strip()
    MAIL_PASSWORD = (os.environ.get("MAIL_PASSWORD") or "").strip()
    MAIL_FROM = os.environ.get("MAIL_FROM") or ""
    MAIL_TO = os.environ.get("MAIL_TO") or "sergeymarkin@yandex.ru"
    MAIL_SMTP_DUAL_TRY = os.environ.get("MAIL_SMTP_DUAL_TRY", "true").lower() in (
        "1",
        "true",
        "yes",
    )
    MAIL_SMTP_TIMEOUT = int(os.environ.get("MAIL_SMTP_TIMEOUT") or "12")
    MAIL_SMTP_FORCE_IPV4 = os.environ.get("MAIL_SMTP_FORCE_IPV4", "true").lower() in (
        "1",
        "true",
        "yes",
    )

    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or ""
    TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID") or ""


def get_notify_config() -> dict[str, Any]:
    return {
        "SITE_URL": Config.SITE_URL,
        "MAIL_SERVER": Config.MAIL_SERVER,
        "MAIL_PORT": Config.MAIL_PORT,
        "MAIL_USE_SSL": Config.MAIL_USE_SSL,
        "MAIL_USERNAME": Config.MAIL_USERNAME,
        "MAIL_PASSWORD": Config.MAIL_PASSWORD,
        "MAIL_FROM": Config.MAIL_FROM,
        "MAIL_TO": Config.MAIL_TO,
        "MAIL_SMTP_DUAL_TRY": Config.MAIL_SMTP_DUAL_TRY,
        "MAIL_SMTP_TIMEOUT": Config.MAIL_SMTP_TIMEOUT,
        "MAIL_SMTP_FORCE_IPV4": Config.MAIL_SMTP_FORCE_IPV4,
        "TELEGRAM_BOT_TOKEN": Config.TELEGRAM_BOT_TOKEN,
        "TELEGRAM_CHAT_ID": Config.TELEGRAM_CHAT_ID,
    }
