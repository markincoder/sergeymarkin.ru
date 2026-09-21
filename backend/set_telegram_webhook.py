# -*- coding: utf-8 -*-
"""Регистрация Telegram webhook из .env: python -m backend.set_telegram_webhook"""
from __future__ import annotations

import json
import sys

import requests

from config import Config


def webhook_url() -> str:
    site = (Config.SITE_URL or "").rstrip("/")
    secret = (Config.TELEGRAM_WEBHOOK_SECRET or "").strip()
    if not site:
        raise SystemExit("SITE_URL пустой")
    url = f"{site}/api/telegram/webhook"
    if secret:
        url = f"{url}?secret={secret}"
    return url


def main() -> None:
    token = (Config.TELEGRAM_BOT_TOKEN or "").strip()
    secret = (Config.TELEGRAM_WEBHOOK_SECRET or "").strip()
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN пустой")
    if not secret:
        raise SystemExit("TELEGRAM_WEBHOOK_SECRET пустой")

    url = webhook_url()
    r = requests.post(
        f"https://api.telegram.org/bot{token}/setWebhook",
        data={
            "url": url,
            "secret_token": secret,
            "allowed_updates": json.dumps(["message", "edited_message"]),
        },
        timeout=20,
    )
    body = r.json()
    print("setWebhook:", json.dumps(body, ensure_ascii=False))
    info = requests.get(f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=15).json()
    result = (info.get("result") or {})
    print(
        "getWebhookInfo:",
        json.dumps(
            {
                "url": result.get("url"),
                "pending_update_count": result.get("pending_update_count"),
                "last_error_message": result.get("last_error_message") or "",
            },
            ensure_ascii=False,
        ),
    )
    if not body.get("ok"):
        sys.exit(1)


if __name__ == "__main__":
    main()
