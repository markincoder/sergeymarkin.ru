# -*- coding: utf-8 -*-
"""Защита от спама для формы обратной связи.

Включает:
1. Блок-лист ключевых слов (казино, крипта, спам-шаблоны).
2. Блок-лист одноразовых почтовых доменов и заблокированных адресов.
3. Блок-лист IP-адресов.
4. Проверка скорости заполнения формы (Timing Token): боты отправляют форму мгновенно.
5. IP Rate Limiting (ограничение частоты обращений).
6. Невидимый Honeypot.
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from starlette.requests import Request

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
BLOCKLIST_FILE = BASE_DIR / "database" / "spam_blocklist.json"

# Базовые спам-домены (одноразовая почта и известные спам-боты)
DEFAULT_BLOCKED_DOMAINS = [
    "mailnesia.com",
    "guerrillamail.com",
    "tempmail.com",
    "temp-mail.org",
    "10minutemail.com",
    "dispostable.com",
    "yopmail.com",
    "sharklasers.com",
    "getnada.com",
    "mohmal.com",
    "burnermail.io",
    "trashmail.com",
    "crazymailing.com",
]

# Базовые спам-слова и фразы
DEFAULT_BLOCKED_KEYWORDS = [
    "1xbet",
    "vavada",
    "казино",
    "casino",
    "игровые автоматы",
    "free spins",
    "фриспины",
    "криптовалют",
    "crypto trading",
    "crypto investment",
    "earn bitcoin",
    "viagra",
    "виагра",
    "cialis",
    "виагру",
    "порно",
    "adult dating",
    "seo backlinks",
    "backlink",
    "ranking on google",
    "трафик на сайт дешево",
    "продвижение сайтов спам",
    "быстрый займ",
    "микрозайм",
    "кредит без отказа",
    "whatsapp рассылк",
    "массовая рассылка telegram",
]

# Ограничение частоты (IP -> list[float timestamps])
_ip_requests: dict[str, list[float]] = {}


def _get_client_ip(request: Request) -> str:
    """Определить IP клиента с учётом прокси."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "127.0.0.1"


def _ensure_blocklist_file() -> dict[str, Any]:
    """Загрузить или создать spam_blocklist.json."""
    if not BLOCKLIST_FILE.exists():
        BLOCKLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
        initial_data = {
            "blocked_domains": DEFAULT_BLOCKED_DOMAINS,
            "blocked_keywords": DEFAULT_BLOCKED_KEYWORDS,
            "blocked_emails": [],
            "blocked_ips": [],
        }
        try:
            with open(BLOCKLIST_FILE, "w", encoding="utf-8") as f:
                json.dump(initial_data, f, ensure_ascii=False, indent=2)
            return initial_data
        except Exception as e:
            logger.warning("Не удалось записать %s: %s", BLOCKLIST_FILE, e)
            return initial_data

    try:
        with open(BLOCKLIST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Ошибка чтения %s: %s", BLOCKLIST_FILE, e)
        return {
            "blocked_domains": DEFAULT_BLOCKED_DOMAINS,
            "blocked_keywords": DEFAULT_BLOCKED_KEYWORDS,
            "blocked_emails": [],
            "blocked_ips": [],
        }


def check_rate_limit(ip: str, max_requests: int = 4, window_seconds: int = 600) -> bool:
    """Проверка rate limit: не более max_requests запросов за window_seconds."""
    now = time.time()
    history = _ip_requests.setdefault(ip, [])
    # Очистка устаревших записей
    _ip_requests[ip] = [t for t in history if now - t < window_seconds]
    if len(_ip_requests[ip]) >= max_requests:
        return False
    _ip_requests[ip].append(now)
    return True


def check_submission_for_spam(
    request: Request,
    *,
    name: str,
    email: str,
    phone: str,
    subject: str,
    body: str,
    website: str,
    min_fill_seconds: float = 2.5,
) -> tuple[bool, str]:
    """Проверить отправку на спам.

    Возвращает:
        (is_spam: bool, reason: str)
    """
    ip = _get_client_ip(request)

    # 1. Honeypot check (скрытое поле)
    if (website or "").strip():
        return True, f"Honeypot filled ({website.strip()[:30]})"

    # 2. Timing token check (боты отправляют форму за < 2.5 сек)
    form_opened_at = request.session.pop("contact_opened_at", None)
    if form_opened_at:
        try:
            elapsed = time.time() - float(form_opened_at)
            if elapsed < min_fill_seconds:
                return True, f"Submitted too quickly ({elapsed:.2f}s < {min_fill_seconds}s)"
        except (ValueError, TypeError):
            pass

    # 3. Rate-limit check
    if not check_rate_limit(ip):
        return True, f"Rate limit exceeded for IP {ip}"

    # 4. Блок-лист
    blocklist = _ensure_blocklist_file()
    blocked_ips = set(blocklist.get("blocked_ips", []))
    if ip in blocked_ips:
        return True, f"IP {ip} is in blocklist"

    clean_email = (email or "").strip().lower()
    blocked_emails = set(e.lower() for e in blocklist.get("blocked_emails", []))
    if clean_email in blocked_emails:
        return True, f"Email {clean_email} is in blocklist"

    # Проверка домена email
    if "@" in clean_email:
        domain = clean_email.split("@", 1)[1]
        blocked_domains = [d.lower() for d in blocklist.get("blocked_domains", [])]
        for b_dom in blocked_domains:
            if domain == b_dom or domain.endswith("." + b_dom):
                return True, f"Email domain {domain} is in spam blocklist"

    # 5. Проверка спам-слов в теме, имени и сообщении
    all_text = f"{name} {subject} {body}".lower()
    blocked_keywords = [k.lower() for k in blocklist.get("blocked_keywords", [])]
    for kw in blocked_keywords:
        if kw in all_text:
            return True, f"Spam keyword detected: '{kw}'"

    # 6. Проверка ссылочного спама: если в теле сообщения > 3 ссылок
    url_count = len(re.findall(r"https?://|www\.", all_text))
    if url_count > 3:
        return True, f"Too many URLs in message ({url_count})"

    return False, ""
