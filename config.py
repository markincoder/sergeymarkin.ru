# -*- coding: utf-8 -*-
"""Конфигурация приложения Flask."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Корень проекта (где лежит config.py и .env) — подхватываем переменные для локального запуска и Docker
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class Config:
    """Базовые настройки."""

    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-change-me-in-production"
    # SQLite: файл в папке database/
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or (
        "sqlite:///" + str(BASE_DIR / "database" / "app.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Flask-WTF / CSRF
    WTF_CSRF_ENABLED = True

    # Админ по умолчанию (смените через переменные окружения в продакшене)
    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME") or "admin"
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD") or "admin123"

    # Логирование
    LOG_LEVEL = os.environ.get("LOG_LEVEL") or "INFO"

    # SEO: канонический домен (без слэша в конце) — см. SEO-инструкция.md
    SITE_URL = os.environ.get("SITE_URL") or "https://sergeymarkin.ru"
    # Картинка по умолчанию для Open Graph (путь от корня сайта)
    SEO_OG_IMAGE = os.environ.get("SEO_OG_IMAGE") or "/static/images/hero-profile.svg"

    # --- Уведомления о заявках (почта + Telegram) ---
    # SMTP: например smtp.yandex.ru или smtp.gmail.com; пароль приложения у провайдера, не обычный пароль.
    MAIL_SERVER = os.environ.get("MAIL_SERVER") or "smtp.yandex.ru"
    MAIL_PORT = int(os.environ.get("MAIL_PORT") or "465")
    MAIL_USE_SSL = os.environ.get("MAIL_USE_SSL", "true").lower() in ("1", "true", "yes")
    MAIL_USERNAME = (os.environ.get("MAIL_USERNAME") or "").strip()
    MAIL_PASSWORD = (os.environ.get("MAIL_PASSWORD") or "").strip()
    MAIL_FROM = os.environ.get("MAIL_FROM") or ""  # если пусто — как MAIL_USERNAME
    MAIL_TO = os.environ.get("MAIL_TO") or "sergeymarkin@yandex.ru"
    # SMTP: на VPS часто блокируют исходящий 465 — по умолчанию сначала 587, потом 465
    MAIL_SMTP_DUAL_TRY = os.environ.get("MAIL_SMTP_DUAL_TRY", "true").lower() in (
        "1",
        "true",
        "yes",
    )
    MAIL_SMTP_TIMEOUT = int(os.environ.get("MAIL_SMTP_TIMEOUT") or "12")
    # Только IPv4: в Docker часто нет маршрута до IPv6 → «Network is unreachable» на smtp.yandex.ru
    MAIL_SMTP_FORCE_IPV4 = os.environ.get("MAIL_SMTP_FORCE_IPV4", "true").lower() in (
        "1",
        "true",
        "yes",
    )

    # Telegram: создайте бота у @BotFather, затем узнайте chat_id (число) — напишите боту /start,
    # откройте https://api.telegram.org/bot<TOKEN>/getUpdates или @userinfobot
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or ""
    TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID") or ""
