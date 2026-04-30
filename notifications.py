# -*- coding: utf-8 -*-
"""Уведомления: email (SMTP) и Telegram."""
from __future__ import annotations

import logging
import smtplib
import socket
from email.message import EmailMessage
from typing import Any, Mapping

import requests

logger = logging.getLogger(__name__)


def _telegram_chat_id_for_api(chat_id: str) -> int | str:
    s = (chat_id or "").strip()
    if not s or s.startswith("@"):
        return s
    try:
        return int(s)
    except ValueError:
        return s


def _telegram_send_payload_base(cfg: Mapping[str, Any], text: str) -> dict[str, Any]:
    chat_id_raw = (cfg.get("TELEGRAM_CHAT_ID") or "").strip()
    payload: dict[str, Any] = {
        "chat_id": _telegram_chat_id_for_api(chat_id_raw),
        "text": text[:4096],
    }
    mt = (cfg.get("TELEGRAM_MESSAGE_THREAD_ID") or "").strip()
    if mt:
        try:
            payload["message_thread_id"] = int(mt)
        except ValueError:
            logger.warning("TELEGRAM_MESSAGE_THREAD_ID is not an integer: %s", mt)
    return payload


def _smtp_send(
    cfg: Mapping[str, Any],
    *,
    mail_from: str,
    mail_to: str,
    subject: str,
    text_body: str,
) -> None:
    server = cfg["MAIL_SERVER"]
    port = int(cfg["MAIL_PORT"])
    use_ssl = bool(cfg["MAIL_USE_SSL"])
    username = (cfg.get("MAIL_USERNAME") or "").strip()
    password = (cfg.get("MAIL_PASSWORD") or "").strip()
    dual_try = bool(cfg.get("MAIL_SMTP_DUAL_TRY", True))
    timeout = int(cfg.get("MAIL_SMTP_TIMEOUT", 12))
    force_ipv4 = bool(cfg.get("MAIL_SMTP_FORCE_IPV4", True))

    def _connect() -> smtplib.SMTP_SSL | smtplib.SMTP:
        if force_ipv4:
            orig_getaddrinfo = socket.getaddrinfo

            def _getaddrinfo_ipv4(
                host: Any,
                port: Any,
                family: int = 0,
                type: int = 0,
                proto: int = 0,
                flags: int = 0,
            ) -> Any:
                return orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

            socket.getaddrinfo = _getaddrinfo_ipv4  # type: ignore[assignment]
            try:
                if use_ssl:
                    return smtplib.SMTP_SSL(server, port, timeout=timeout)
                smtp = smtplib.SMTP(server, port, timeout=timeout)
                smtp.starttls()
                return smtp
            finally:
                socket.getaddrinfo = orig_getaddrinfo  # type: ignore[assignment]
        if use_ssl:
            return smtplib.SMTP_SSL(server, port, timeout=timeout)
        smtp = smtplib.SMTP(server, port, timeout=timeout)
        smtp.starttls()
        return smtp

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = mail_to
    msg.set_content(text_body)

    last_err: Exception | None = None
    for attempt in (1, 2) if dual_try else (1,):
        try:
            with _connect() as smtp:
                if username:
                    smtp.login(username, password)
                smtp.send_message(msg)
            return
        except Exception as e:
            last_err = e
            logger.warning("SMTP attempt %s failed: %s", attempt, e)
    if last_err:
        raise last_err


def send_email_notification(
    cfg: Mapping[str, Any],
    *,
    subject: str,
    text_body: str,
) -> None:
    mail_from = (cfg.get("MAIL_FROM") or cfg.get("MAIL_USERNAME") or "").strip()
    mail_to = (cfg.get("MAIL_TO") or "").strip()
    if not mail_from or not mail_to:
        logger.warning("Email not configured: MAIL_FROM/MAIL_TO")
        return
    _smtp_send(cfg, mail_from=mail_from, mail_to=mail_to, subject=subject, text_body=text_body)


def send_telegram_notification(
    cfg: Mapping[str, Any],
    *,
    text: str,
) -> None:
    token = (cfg.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (cfg.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        logger.warning("Telegram not configured")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = _telegram_send_payload_base(cfg, text)
    r = requests.post(url, json=payload, timeout=15)
    r.raise_for_status()


def send_telegram_bot_message(
    cfg: Mapping[str, Any],
    *,
    text: str,
    reply_to_message_id: int | None = None,
) -> int:
    """Отправка от имени бота; возвращает message_id (для reply и карты сессий)."""
    token = (cfg.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (cfg.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        raise RuntimeError("Telegram not configured")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    base = _telegram_send_payload_base(cfg, text)
    payload = dict(base)
    if reply_to_message_id is not None:
        payload["reply_to_message_id"] = int(reply_to_message_id)
    r = requests.post(url, json=payload, timeout=15)
    if r.status_code == 400 and reply_to_message_id is not None:
        try:
            desc = (r.json() or {}).get("description", r.text)
        except Exception:
            desc = r.text
        logger.warning(
            "Telegram sendMessage with reply_to_message_id=%s: %s — retrying without reply_to",
            reply_to_message_id,
            desc,
        )
        r = requests.post(url, json=base, timeout=15)
    if not r.ok:
        try:
            desc = (r.json() or {}).get("description", r.text)
        except Exception:
            desc = r.text
        logger.error("Telegram sendMessage failed: %s", desc)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(str(data.get("description", data)))
    return int(data["result"]["message_id"])


def notify_contact_submission(
    cfg: Mapping[str, Any],
    *,
    name: str,
    email: str,
    phone: str,
    subject: str,
    body: str | None,
) -> None:
    site = cfg.get("SITE_URL", "")
    text = (
        f"Новая заявка с сайта {site}\n\n"
        f"Имя: {name}\n"
        f"Email: {email}\n"
        f"Телефон: {phone}\n"
        f"Тема: {subject}\n"
    )
    if body:
        text += f"\nСообщение:\n{body}\n"

    try:
        send_email_notification(
            cfg,
            subject=f"[Сайт] {subject}",
            text_body=text,
        )
    except Exception as e:
        logger.exception("Email notify failed: %s", e)

    try:
        send_telegram_notification(cfg, text=text)
    except Exception as e:
        logger.exception("Telegram notify failed: %s", e)
