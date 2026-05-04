# -*- coding: utf-8 -*-
"""Конфигурация приложения (FastAPI)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
# utf-8-sig: BOM из Windows не ломает имя переменной OPENAI_API_KEY
# override=True: значения из .env должны перекрывать пустые/устаревшие переменные окружения ОС
# (иначе пустая TELEGRAM_WEBHOOK_SECRET в системе блокирует секрет из файла).
load_dotenv(BASE_DIR / ".env", encoding="utf-8-sig", override=True)

from backend.openai_key import openai_api_key  # noqa: E402

# FAQ/RAG: database/rag_data/ рядом с SQLite (database/app.db). В Docker том смонтирован на /app/database — держите rag_data в том же томе.
RAG_DATA_DIR = BASE_DIR / "database" / "rag_data"


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
    # Через запятую origins для CORS (например https://www.site.ru,https://site.ru). Нужно, если HTML с одного origin, а CHAT_API_BASE — с другого.
    CORS_ALLOW_ORIGINS = (os.environ.get("CORS_ALLOW_ORIGINS") or "").strip()
    OPENAI_API_KEY = (os.environ.get("OPENAI_API_KEY") or "").strip()  # см. openai_api_key()

    # Компактная строка тематики для промпта RAG-чата (ниже фрагменты из индекса; весь сайт в запрос не грузится).
    CHAT_RAG_THEME_LINE = (os.environ.get("CHAT_RAG_THEME_LINE") or "").strip() or (
        "Сергей Маркин — prompt engineer: промпты и вайб-кодинг, чат-боты с RAG, n8n и связки сервисов, "
        "интеграции LLM для бизнеса, сокращение рутины; на сайте — кейсы, контакты, условия в общих чертах."
    )

    # Слабое попадание в FAISS (L2): если лучший фрагмент дальше порога — при «да» классификатора темы эскалация в Telegram.
    RAG_HANDOFF_L2_MAX = float(os.environ.get("RAG_HANDOFF_L2_MAX") or "1.25")

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
    # Для супергруппы с темами (forum): id ветки (topic), иначе reply к якорю иногда даёт 400.
    TELEGRAM_MESSAGE_THREAD_ID = (os.environ.get("TELEGRAM_MESSAGE_THREAD_ID") or "").strip()
    # Секрет для webhook (значение из setWebhook secret_token → заголовок X-Telegram-Bot-Api-Secret-Token).
    TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET") or ""
    # Сообщение посетителю в виджете после команды оператора завершить чат (/end и т.д.).
    OPERATOR_CHAT_CLOSURE_MESSAGE = (os.environ.get("OPERATOR_CHAT_CLOSURE_MESSAGE") or "").strip() or (
        "Оператор завершил консультацию. Диалог снова ведёт автоматический помощник по материалам сайта — "
        "можете задать следующий вопрос здесь."
    )


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
        "TELEGRAM_MESSAGE_THREAD_ID": Config.TELEGRAM_MESSAGE_THREAD_ID,
    }
