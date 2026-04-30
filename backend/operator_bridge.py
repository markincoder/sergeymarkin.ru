# -*- coding: utf-8 -*-
"""Эскалация чата к оператору через Telegram: сессии в БД, привязка reply."""
from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Callable, Mapping

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from models import ChatBridgeLine, ChatBridgeSession, TelegramBridgeMap

logger = logging.getLogger(__name__)

_SITE = re.compile(r"https?://[^\s]+", re.I)
# Текст сообщения оператора / цитаты: session: …, сессия=…, либо голый UUID активной сессии operator.
_SESSION_TOKEN = re.compile(
    r"(?i)(?:session|сессия)\s*[:=]\s*"
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b"
)
_ANY_UUID = re.compile(
    r"\b([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b",
    re.I,
)
# Целая строка — только служебная привязка сессии (не показывать посетителю).
_ROUTING_LINE = re.compile(
    r"(?i)^\s*(?:session|сессия)\s*[:=]\s*[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\s*$"
)
_UUID_ONLY_LINE = re.compile(
    r"^\s*[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\s*$",
    re.I,
)
# «session: uuid остальной текст» в одной строке.
_LINE_LEADING_SESSION = re.compile(
    r"(?i)^\s*(?:session|сессия)\s*[:=]\s*[0-9a-f]{8}(?:-[0-9a-f]{4}){4}-[0-9a-f]{12}\b\s+(\S.*)$"
)

# Явная просьба перевести на человека (подстрока, lower).
_EXPLICIT_HUMAN_PHRASES: tuple[str, ...] = (
    "переведи на оператора",
    "перевести на оператора",
    "соедини с оператором",
    "соедините с оператором",
    "переключи на оператора",
    "переключите на оператора",
    "живой оператор",
    "нужен человек",
    "нужен живой человек",
    "соедини с человеком",
    "соедините с человеком",
    "позови человека",
    "позовите человека",
    "хочу поговорить с человеком",
    "связь с оператором",
    "позови оператора",
    "переведи на человека",
    "соедини с менеджером",
    "хочу живого человека",
)


def wants_explicit_human_handoff(text: str) -> bool:
    t = text.lower().strip()
    if len(t) < 3:
        return False
    return any(p in t for p in _EXPLICIT_HUMAN_PHRASES)


def strip_operator_routing_metadata(text: str) -> str:
    """Убрать session:/сессия: и ведущие строки-UUID из ответа оператора для виджета на сайте."""
    raw = (text or "").replace("\r\n", "\n").strip()
    if not raw:
        return ""
    lines = raw.split("\n")
    out: list[str] = []
    skip_leading_uuid = True
    for line in lines:
        if _ROUTING_LINE.match(line):
            continue
        if skip_leading_uuid and _UUID_ONLY_LINE.match(line):
            continue
        skip_leading_uuid = False
        m = _LINE_LEADING_SESSION.match(line)
        if m:
            out.append(m.group(1).strip())
            continue
        out.append(line)
    return "\n".join(out).strip()


def parse_operator_close_command(text: str) -> str | None:
    """
    Команда завершения чата оператором. None — не команда; иначе текст для посетителя
    (пустая строка = взять дефолт из конфига).
    Поддержка: /end, /close, /stop, /завершить, /закрыть и произвольный текст после пробела/переноса.
    """
    body = (strip_operator_routing_metadata(text) or "").strip()
    if not body:
        return None
    m = re.match(
        r"(?is)^(?:/end|/close|/stop|/завершить|/закрыть)(?:\s+([\s\S]+))?\s*$",
        body,
    )
    if not m:
        return None
    return (m.group(1) or "").strip()


def close_session_by_operator(db: Session, session_id: str, visitor_notice: str) -> None:
    """Вернуть сессию в RAG, очистить привязку Telegram, поставить уведомление для poll виджета."""
    sess = db.get(ChatBridgeSession, session_id)
    if sess is None:
        return
    sess.mode = "rag"
    sess.telegram_anchor_id = None
    sess.handoff_confirm_pending = False
    sess.closure_pending_message = visitor_notice
    db.execute(delete(TelegramBridgeMap).where(TelegramBridgeMap.session_id == session_id))
    db.add(sess)
    db.commit()


def release_operator_line_to_rag(db: Session, session_id: str) -> None:
    """Вернуть чат в режим FAQ без уведомления (например короткое «добрый день» при залипшей operator-сессии)."""
    sess = db.get(ChatBridgeSession, session_id)
    if sess is None:
        return
    sess.mode = "rag"
    sess.telegram_anchor_id = None
    sess.handoff_confirm_pending = False
    db.execute(delete(TelegramBridgeMap).where(TelegramBridgeMap.session_id == session_id))
    db.add(sess)
    db.commit()


def new_session_id() -> str:
    return str(uuid.uuid4())


def session_has_prior_assistant_message(db: Session, session_id: str) -> bool:
    """Уже был ответ ассистента (RAG/подтверждение в чате) — можно трактовать короткие реплики как уточнения."""
    one = db.scalar(
        select(ChatBridgeLine.id).where(
            ChatBridgeLine.session_id == session_id,
            ChatBridgeLine.role == "assistant",
        ).limit(1)
    )
    return one is not None


def get_or_create_session(db: Session, session_id: str | None) -> tuple[str, ChatBridgeSession]:
    sid = (session_id or "").strip() or new_session_id()
    row = db.get(ChatBridgeSession, sid)
    if row is None:
        row = ChatBridgeSession(session_id=sid, mode="rag")
        db.add(row)
        db.commit()
        db.refresh(row)
    return sid, row


def add_line(db: Session, session_id: str, role: str, content: str, *, op_seq: int | None = None) -> ChatBridgeLine:
    line = ChatBridgeLine(session_id=session_id, role=role, content=content, op_seq=op_seq)
    db.add(line)
    db.commit()
    db.refresh(line)
    return line


def append_operator_message(db: Session, session_id: str, text: str) -> tuple[int, int] | None:
    """Добавить реплику оператора; в БД — без служебных строк session:/UUID. None если после очистки текста нет."""
    clean = strip_operator_routing_metadata(text)
    if not clean:
        return None
    next_seq = (
        db.scalar(
            select(func.coalesce(func.max(ChatBridgeLine.op_seq), 0)).where(
                ChatBridgeLine.session_id == session_id,
                ChatBridgeLine.op_seq.is_not(None),
            )
        )
        or 0
    ) + 1
    line = ChatBridgeLine(session_id=session_id, role="operator", content=clean, op_seq=next_seq)
    db.add(line)
    db.commit()
    db.refresh(line)
    return line.id, next_seq


def transcript_lines(db: Session, session_id: str) -> list[ChatBridgeLine]:
    return list(
        db.scalars(
            select(ChatBridgeLine).where(ChatBridgeLine.session_id == session_id).order_by(ChatBridgeLine.id)
        ).all()
    )


def format_transcript_for_telegram(db: Session, session_id: str) -> str:
    label = {"user": "Посетитель", "assistant": "Бот (RAG)", "operator": "Оператор"}
    parts: list[str] = []
    for ln in transcript_lines(db, session_id):
        tag = label.get(ln.role, ln.role)
        parts.append(f"{tag}: {ln.content}")
    return "\n".join(parts) if parts else "(пусто)"


def register_bot_telegram_message(db: Session, telegram_msg_id: int, session_id: str) -> None:
    db.merge(TelegramBridgeMap(telegram_msg_id=int(telegram_msg_id), session_id=session_id))
    db.commit()


def resolve_session_from_plain_text(db: Session, text: str) -> str | None:
    """Найти session_id в свободном тексте (ответ оператора без Reply). Только сессии в режиме operator."""
    t = (text or "").strip()
    if not t:
        return None
    m = _SESSION_TOKEN.search(t)
    if m:
        sid = m.group(1).strip()
        row = db.get(ChatBridgeSession, sid)
        if row and row.mode == "operator":
            return sid
    for um in _ANY_UUID.finditer(t):
        sid = um.group(1)
        row = db.get(ChatBridgeSession, sid)
        if row and row.mode == "operator":
            return sid
    return None


def resolve_session_from_reply_chain(db: Session, reply_to: dict[str, Any] | None) -> str | None:
    cur: dict[str, Any] | None = reply_to
    while cur:
        mid = cur.get("message_id")
        if mid is not None:
            row = db.get(TelegramBridgeMap, int(mid))
            if row:
                return row.session_id
        blob = (cur.get("text") or cur.get("caption") or "").strip()
        if blob:
            sid = resolve_session_from_plain_text(db, blob)
            if sid:
                return sid
        nxt = cur.get("reply_to_message")
        cur = nxt if isinstance(nxt, dict) else None
    return None


def _telegram_configured(cfg: Mapping[str, Any]) -> bool:
    return bool((cfg.get("TELEGRAM_BOT_TOKEN") or "").strip() and (cfg.get("TELEGRAM_CHAT_ID") or "").strip())


def notify_handoff(
    db: Session,
    session_id: str,
    cfg: Mapping[str, Any],
    send_message: Callable[..., int],
) -> bool:
    """Первое уведомление оператору с историей. True если отправлено."""
    if not _telegram_configured(cfg):
        logger.warning("Operator handoff skipped: Telegram not configured")
        return False
    sess = db.get(ChatBridgeSession, session_id)
    if not sess:
        return False
    body = format_transcript_for_telegram(db, session_id)
    text = (
        "🔔 Чат сайта — нужен оператор\n\n"
        "Чтобы ответ попал посетителю в виджет на сайте:\n"
        "• Нажмите «Ответить» на это сообщение бота и напишите текст; или\n"
        "• В любой ответ в этот чат вставьте строку (можно одной первой строкой):\n"
        f"session: {session_id}\n\n"
        "Завершить консультацию с посетителем: /end или /закрыть (опционально свой текст: /end Спасибо за обращение).\n\n"
        "--- История чата ---\n"
        f"{body}"
    )
    if len(text) > 4000:
        text = text[:3997] + "..."
    try:
        mid = send_message(cfg, text=text, reply_to_message_id=None)
    except Exception as e:
        logger.exception("Telegram handoff failed: %s", e)
        return False
    register_bot_telegram_message(db, mid, session_id)
    sess.telegram_anchor_id = mid
    sess.mode = "operator"
    sess.handoff_confirm_pending = False
    db.add(sess)
    db.commit()
    return True


def notify_visitor_message_in_operator_thread(
    db: Session,
    session_id: str,
    visitor_text: str,
    cfg: Mapping[str, Any],
    send_message: Callable[..., int],
) -> bool:
    """Посетитель написал ещё сообщение в режиме оператора — дублируем в Telegram."""
    if not _telegram_configured(cfg):
        return False
    sess = db.get(ChatBridgeSession, session_id)
    if not sess or not sess.telegram_anchor_id:
        return False
    safe = _SITE.sub("(ссылка)", visitor_text)
    line = (
        "💬 Ещё сообщение от посетителя (сайт)\n\n"
        "Ответ в виджет: «Ответить» на это сообщение бота или вставьте в текст ответа:\n"
        f"session: {session_id}\n"
        "Завершить консультацию: /end или /закрыть.\n\n"
        f"{safe}"
    )
    if len(line) > 4000:
        line = line[:3997] + "..."
    try:
        mid = send_message(
            cfg,
            text=line,
            reply_to_message_id=int(sess.telegram_anchor_id),
        )
    except Exception as e:
        logger.exception("Telegram visitor follow-up failed: %s", e)
        return False
    register_bot_telegram_message(db, mid, session_id)
    sess.telegram_anchor_id = mid
    db.add(sess)
    db.commit()
    return True


def list_operator_messages_after(db: Session, session_id: str, after_op_seq: int) -> list[dict[str, Any]]:
    """Сообщения оператора с op_seq > after_op_seq (для long-polling виджета)."""
    rows = db.scalars(
        select(ChatBridgeLine)
        .where(
            ChatBridgeLine.session_id == session_id,
            ChatBridgeLine.role == "operator",
            ChatBridgeLine.op_seq.is_not(None),
            ChatBridgeLine.op_seq > after_op_seq,
        )
        .order_by(ChatBridgeLine.op_seq)
    ).all()
    return [{"seq": int(r.op_seq), "text": r.content} for r in rows]
