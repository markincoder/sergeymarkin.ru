# -*- coding: utf-8 -*-
"""RAG чат: APIRouter для FastAPI."""
from __future__ import annotations

import logging
import os
import re
import unicodedata
from typing import Any

import numpy as np
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Request, Response
from openai import APIError, OpenAI, PermissionDeniedError
from pydantic import BaseModel, Field

from config import BASE_DIR, Config, RAG_DATA_DIR, get_notify_config

from .chat_intent_patterns import CASUAL_SOCIAL_RE, FOLLOW_HINT_RE, QUESTION_HINT_RE
from .openai_key import openai_api_key

from .operator_bridge import (
    add_line,
    append_operator_message,
    close_session_by_operator,
    get_or_create_session,
    list_operator_messages_after,
    notify_handoff,
    notify_visitor_message_in_operator_thread,
    parse_operator_close_command,
    release_operator_line_to_rag,
    resolve_session_from_plain_text,
    resolve_session_from_reply_chain,
    session_has_prior_assistant_message,
    wants_explicit_human_handoff,
)
from .rag_index import load_index, search_similar
from db import SessionLocal
from models import ChatBridgeSession
from notifications import send_telegram_bot_message

logger = logging.getLogger(__name__)


def telegram_chat_matches_config(tg_chat_id: Any, cfg_chat_id: str) -> bool:
    """Совпадение chat id из update с TELEGRAM_CHAT_ID (строка/число, в т.ч. -100…)."""
    a = (cfg_chat_id or "").strip()
    if tg_chat_id is None or not a:
        return False
    b = str(tg_chat_id).strip()
    if a == b:
        return True
    try:
        return int(a) == int(b)
    except ValueError:
        return False


# Текст оператора без reply: session в тексте — resolve_session_from_plain_text.

# Публичный URL сайта; индексация страниц при запросе не выполняется — только эмбеддинг вопроса + поиск в FAISS.
_CHAT_SITE = (Config.SITE_URL or "https://sergeymarkin.ru").rstrip("/")

router = APIRouter(prefix="/api", tags=["rag"])


def _telegram_webhook_secret_live() -> str:
    """Секрет из актуального .env (перечитать при запросе — иначе несохранённый редактор и старый процесс дают 503)."""
    load_dotenv(BASE_DIR / ".env", encoding="utf-8-sig", override=True)
    return (os.environ.get("TELEGRAM_WEBHOOK_SECRET") or "").strip()


_index: Any = None
_metadata: Any = None
_client: OpenAI | None = None


def init_rag() -> None:
    """Загрузить индекс и клиент OpenAI (при старте приложения)."""
    global _index, _metadata, _client
    load_dotenv(BASE_DIR / ".env", encoding="utf-8-sig", override=True)

    index_path = str(RAG_DATA_DIR / "faiss_index.bin")
    meta_path = str(RAG_DATA_DIR / "faqs_metadata.npy")
    try:
        _index, _metadata = load_index(index_path, meta_path)
        logger.info("RAG: индекс загружен из %s", RAG_DATA_DIR)
    except Exception as e:
        _index, _metadata = None, None
        logger.warning("RAG: индекс не загружен: %s", e)

    key = openai_api_key()
    _client = OpenAI(api_key=key) if key else None
    if not key:
        logger.warning("RAG: OPENAI_API_KEY пустой в окружении (проверьте env_file в docker-compose и имя переменной).")
    elif _index is None:
        logger.warning(
            "RAG: нет индекса в %s — локально: python -m backend.build_index; в Docker индекс должен быть в образе.",
            RAG_DATA_DIR,
        )


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=40)


def _hits_to_labeled_context(hits: list[Any]) -> str:
    """Собрать контекст для LLM: каждый фрагмент с явным именем источника из базы знаний."""
    parts: list[str] = []
    for i, h in enumerate(hits, start=1):
        if not isinstance(h, dict):
            parts.append(f"### Фрагмент {i}\n{h}")
            continue
        src = (h.get("source") or "база знаний").strip()
        q = (h.get("question") or "").strip()
        a = (h.get("answer") or "").strip()
        parts.append(
            f"### Фрагмент {i}\nИсточник (файл/раздел): {src}\n"
            f"Заголовок или вопрос: {q}\nТекст: {a}"
        )
    return "\n\n---\n\n".join(parts) if parts else "(в базе знаний нет подобранных фрагментов)"


def _embed(text: str) -> np.ndarray:
    assert _client is not None
    r = _client.embeddings.create(model="text-embedding-3-small", input=[text])
    vec = np.array([r.data[0].embedding], dtype="float32")
    return vec


def _rag_unavailable_detail() -> str:
    parts = []
    if not openai_api_key():
        parts.append("не задан OPENAI_API_KEY в окружении контейнера (docker compose env_file → sergeymarkin/.env)")
    if _index is None or _metadata is None:
        parts.append(
            "нет FAISS-индекса в database/rag_data — выполните `python -m backend.build_index`; "
            "в Docker каталог в томе `/app/database` рядом с SQLite (скопируйте `rag_data` при деплое, либо держите его в репозитории и пересоберите образ)."
        )
    return "Чат недоступен: " + ("; ".join(parts) if parts else "сервис не инициализирован.")


def _telegram_ready(cfg: dict[str, Any]) -> bool:
    return bool((cfg.get("TELEGRAM_BOT_TOKEN") or "").strip() and (cfg.get("TELEGRAM_CHAT_ID") or "").strip())


def _weak_rag(distances: list[float], threshold: float) -> bool:
    if not distances:
        return True
    return distances[0] > threshold


def _wants_specialist_boundary_reply(text: str) -> bool:
    """Бытовой оффтоп вне коротких приветствий — про зону компетенций."""
    low = text.lower().strip()
    if CASUAL_SOCIAL_RE.search(low):
        return True
    if re.match(r"^(пока|до свидания)\b", low):
        return True
    return False


def _looks_like_question_or_followup(text: str, has_prior_assistant: bool) -> bool:
    """Вопрос или уточнение к прошлому ответу бота; иначе — без RAG (нейтрально или про компетенции)."""
    t = text.strip()
    if not t:
        return False
    low = t.lower()
    # Раньше «?» и QUESTION_HINT_RE — иначе «как дела?» уходит к оператору как «вопрос».
    if CASUAL_SOCIAL_RE.search(low):
        return False
    if "?" in t:
        return True
    if QUESTION_HINT_RE.search(t):
        return True
    if (
        re.match(
            r"^(спасибо|благодарю|thanks|thx|привет|здравствуй|здрасьте|здравствуйте|"
            r"добр(ый|ое|ого)\s+(день|вечер|утро)|хай|hello|hi|пока|до свидания)\b",
            low,
        )
        and "?" not in t
    ):
        return False
    if has_prior_assistant:
        if re.match(r"^(да|нет|ага|угу|неа|yes|no)\s*!?\s*$", low):
            return True
        if FOLLOW_HINT_RE.search(t):
            return True
        if len(t) >= 12 and "спасибо" not in low and "благодар" not in low:
            if (
                re.search(
                    r"(?:переведи|соедини|позови|переключи).{0,80}(?:оператор|человек)"
                    r"|нужен\s+человек|живой\s+оператор",
                    low,
                )
                and "?" not in t
            ):
                return False
            return True
    return False


def _visitor_confirms_operator_handoff(text: str) -> bool:
    """Подтверждение предложения «подключить оператора» или явная просьба о человеке в том же сообщении."""
    if wants_explicit_human_handoff(text):
        return True
    t = (text or "").lower().strip()
    if not t:
        return False
    return bool(
        re.fullmatch(
            r"(да|ага|угу|ок|окей|okay|yes|давай|конечно|подключай(те)?|согласен|согласна)[\s!?.]*",
            t,
        )
    )


def _visitor_declines_operator_handoff(text: str) -> bool:
    t = (text or "").lower().strip()
    return bool(
        re.fullmatch(
            r"(нет|неа|не\s+надо|не\s+нужно|отмена|no|пока\s+нет)[\s!?.]*",
            t,
        )
    )


def _strip_for_standalone_greeting(text: str) -> str:
    """Первая строка + без хвоста из пробелов/эмодзи (чтобы «добрый день 🙂» снимало залипший operator)."""
    t = (text or "").strip().split("\n", 1)[0].strip()
    if not t:
        return ""
    t = t.rstrip()
    while t:
        ch = t[-1]
        cat = unicodedata.category(ch)
        if cat in ("Zs", "Zl", "Zp"):
            t = t[:-1].rstrip()
            continue
        if cat in ("So", "Sk"):
            t = t[:-1].rstrip()
            continue
        break
    return t


_GREETING_ONLY = re.compile(
    r"(здравствуй(те)?|здрасьте|привет|доброе\s+(утро|день|вечер)|добрый\s+(день|вечер|утро)|"
    r"день\s+добрый|вечер\s+добрый|утро\s+доброе|хай|hello|hi|"
    r"good\s+(morning|afternoon|evening))[\s!?.…,:;]*$",
    re.I | re.UNICODE,
)


def _is_standalone_faq_greeting(text: str) -> bool:
    """Только приветствие без вопроса — снимает залипший режим operator (старый session_id в виджете)."""
    t = _strip_for_standalone_greeting(text)
    if not t or "?" in t:
        return False
    return bool(_GREETING_ONLY.fullmatch(t))


def _classify_on_topic(question: str) -> bool:
    assert _client is not None
    r = _client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Отвечай ровно одним словом: ДА или НЕТ."},
            {
                "role": "user",
                "content": (
                    f"Тематика сайта: {Config.CHAT_RAG_THEME_LINE}\n"
                    f"Вопрос посетителя: {question}\n\n"
                    "Вопрос относится к этой тематике или к услугам/контактам в этом контексте? "
                    "Не учитывай, есть ли ответ в базе знаний."
                ),
            },
        ],
        max_tokens=4,
        temperature=0,
    )
    t = (r.choices[0].message.content or "").strip().upper()
    return t.startswith("ДА")


def _run_rag_answer(q: str, context: str) -> str:
    assert _client is not None
    system_prompt = (
        f"Ты ассистент сайта {_CHAT_SITE}.\n"
        f"Тематика ответов (зафиксировано): {Config.CHAT_RAG_THEME_LINE}\n"
        "Источник фактов: только фрагменты в следующем сообщении пользователя (база знаний). "
        "Вне тематики — вежливый отказ в 1–2 предложениях; предложи вопрос про услуги или форму «Обратная связь».\n"
        "Не выдумывай цены, сроки и контакты; если во фрагментах нет ответа — скажи об этом и предложи связаться через сайт.\n"
        "Язык: русский, кратко.\n"
        "Если опираешься на фрагменты — последней строкой точно: Источник: <через запятую значения поля «Источник (файл/раздел)» использованных фрагментов>. "
        "Без релевантных фрагментов — не добавляй выдуманную строку Источник."
    )
    completion = _client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"Сайт: {_CHAT_SITE}.\n\n"
                    f"Фрагменты базы знаний:\n{context}\n\n"
                    f"Вопрос:\n{q}"
                ),
            },
        ],
        temperature=0.3,
        max_tokens=800,
    )
    return (completion.choices[0].message.content or "").strip()


_OFFER_OPERATOR_AFTER_WEAK_RAG = (
    "В материалах сайта и базе знаний нет уверенного ответа на ваш вопрос. "
    "Подключить оператора? Ответьте «да» или «нет»."
)
_HANDOFF_OFFER_DECLINED = (
    "Хорошо. Можете задать другой вопрос по тематике сайта или переформулировать запрос."
)
_OPERATOR_HANDOFF_AFTER_CONFIRM = (
    "Передал вопрос оператору. Ответ появится здесь; при необходимости уточните детали в этом окне."
)
_OPERATOR_HANDOFF_EXPLICIT_MSG = (
    "По вашей просьбе передал диалог оператору. Ответ появится здесь; при необходимости допишите детали в этом окне."
)
_OPERATOR_ACK = "Сообщение передано оператору."
# Явная просьба о человеке, но Telegram не вышел (нет env / ошибка API).
_EXPLICIT_HANDOFF_UNAVAILABLE = (
    "Оператор сейчас недоступен (Telegram не настроен или не удалось отправить уведомление). "
    "Напишите через форму «Обратная связь» на сайте или повторите запрос позже."
)
_ALREADY_WITH_OPERATOR = (
    "Диалог уже у оператора — напишите ваш вопрос в этом окне, ответ появится здесь."
)
# В режиме operator не использовать _NEUTRAL_REPLY (он звучит как FAQ-бот без оператора).
_OPERATOR_IDLE_REPLY = (
    "Вы на связи с оператором. Напишите вопрос по услугам или сайту — ответ появится здесь."
)

_NEUTRAL_REPLY = (
    "Спасибо за сообщение. Если будут вопросы по нашим услугам или содержанию сайта — напишите, отвечу по делу."
)
_SPECIALIST_SCOPE_REPLY = (
    "Я специализируюсь только на тематике этого сайта: разработка ПО, автоматизация процессов с помощью ИИ, "
    "промпты, RAG-боты, интеграции и связки вроде n8n. По личным и бытовым темам не подскажу — задайте вопрос по услугам или материалам сайта."
)


@router.post("/chat")
def chat_post(body: ChatRequest) -> dict[str, Any]:
    if _client is None or _index is None or _metadata is None:
        raise HTTPException(status_code=503, detail=_rag_unavailable_detail())

    q = body.message.strip()
    cfg = get_notify_config()
    db = SessionLocal()
    pending_notice: str | None = None

    def _with_notice(d: dict[str, Any]) -> dict[str, Any]:
        if pending_notice:
            return {**d, "visitor_notice": pending_notice}
        return d

    try:
        sid, bridge = get_or_create_session(db, body.session_id)
        if bridge.closure_pending_message:
            pending_notice = bridge.closure_pending_message
            bridge.closure_pending_message = None
            db.add(bridge)
            db.commit()
        has_prior_assistant = session_has_prior_assistant_message(db, sid)
        add_line(db, sid, "user", q)

        if bridge.mode == "rag" and bridge.handoff_confirm_pending:
            if _visitor_declines_operator_handoff(q):
                bridge.handoff_confirm_pending = False
                db.add(bridge)
                db.commit()
                add_line(db, sid, "assistant", _HANDOFF_OFFER_DECLINED)
                return _with_notice({
                    "answer": _HANDOFF_OFFER_DECLINED,
                    "session_id": sid,
                    "operator_active": False,
                })
            if _visitor_confirms_operator_handoff(q):
                bridge.handoff_confirm_pending = False
                db.add(bridge)
                db.commit()
                if _telegram_ready(cfg):
                    ok = notify_handoff(db, sid, cfg, send_telegram_bot_message)
                    if ok:
                        add_line(db, sid, "assistant", _OPERATOR_HANDOFF_AFTER_CONFIRM)
                        return _with_notice({
                            "answer": _OPERATOR_HANDOFF_AFTER_CONFIRM,
                            "session_id": sid,
                            "operator_active": True,
                        })
                add_line(db, sid, "assistant", _EXPLICIT_HANDOFF_UNAVAILABLE)
                return _with_notice({
                    "answer": _EXPLICIT_HANDOFF_UNAVAILABLE,
                    "session_id": sid,
                    "operator_active": False,
                })
            bridge.handoff_confirm_pending = False
            db.add(bridge)
            db.commit()

        if bridge.mode == "operator":
            # Залипшая operator-сессия (старый session в браузере): только приветствие → снова FAQ.
            if _is_standalone_faq_greeting(q) and not wants_explicit_human_handoff(q):
                release_operator_line_to_rag(db, sid)
                bridge = db.get(ChatBridgeSession, sid)
            else:
                # Явный handoff при уже активном операторе: иначе фраза не считается «вопросом» и даёт не тот тон ответа.
                if wants_explicit_human_handoff(q):
                    add_line(db, sid, "assistant", _ALREADY_WITH_OPERATOR)
                    return _with_notice({
                        "answer": _ALREADY_WITH_OPERATOR,
                        "session_id": sid,
                        "operator_active": True,
                    })
                # Короткие приветствия / не-вопросы не дублируем в Telegram (избегаем шума и ложного «эскалация»).
                if not _looks_like_question_or_followup(q, has_prior_assistant):
                    reply = (
                        _SPECIALIST_SCOPE_REPLY
                        if _wants_specialist_boundary_reply(q)
                        else _OPERATOR_IDLE_REPLY
                    )
                    add_line(db, sid, "assistant", reply)
                    return _with_notice({
                        "answer": reply,
                        "session_id": sid,
                        "operator_active": True,
                    })
                notify_visitor_message_in_operator_thread(db, sid, q, cfg, send_telegram_bot_message)
                add_line(db, sid, "assistant", _OPERATOR_ACK)
                return _with_notice({
                    "answer": _OPERATOR_ACK,
                    "session_id": sid,
                    "operator_active": True,
                })

        if wants_explicit_human_handoff(q):
            if _telegram_ready(cfg):
                ok = notify_handoff(db, sid, cfg, send_telegram_bot_message)
                if ok:
                    add_line(db, sid, "assistant", _OPERATOR_HANDOFF_EXPLICIT_MSG)
                    return _with_notice({
                        "answer": _OPERATOR_HANDOFF_EXPLICIT_MSG,
                        "session_id": sid,
                        "operator_active": True,
                    })
                logger.warning("Explicit handoff failed (Telegram); выдаём явное сообщение, не нейтральный ответ")
            add_line(db, sid, "assistant", _EXPLICIT_HANDOFF_UNAVAILABLE)
            return _with_notice({
                "answer": _EXPLICIT_HANDOFF_UNAVAILABLE,
                "session_id": sid,
                "operator_active": False,
            })

        if not _looks_like_question_or_followup(q, has_prior_assistant):
            reply = (
                _SPECIALIST_SCOPE_REPLY
                if _wants_specialist_boundary_reply(q)
                else _NEUTRAL_REPLY
            )
            add_line(db, sid, "assistant", reply)
            return _with_notice({"answer": reply, "session_id": sid, "operator_active": False})

        try:
            qv = _embed(q)
            hits, dists = search_similar(_index, _metadata, qv, k=3)
            weak = _weak_rag(dists, Config.RAG_HANDOFF_L2_MAX)

            if weak and _telegram_ready(cfg):
                try:
                    on_topic = _classify_on_topic(q)
                except Exception as e:
                    logger.warning("On-topic classify failed: %s", e)
                    on_topic = False
                if on_topic:
                    bridge.handoff_confirm_pending = True
                    db.add(bridge)
                    db.commit()
                    add_line(db, sid, "assistant", _OFFER_OPERATOR_AFTER_WEAK_RAG)
                    return _with_notice({
                        "answer": _OFFER_OPERATOR_AFTER_WEAK_RAG,
                        "session_id": sid,
                        "operator_active": False,
                    })

            context = _hits_to_labeled_context(hits)
            answer = _run_rag_answer(q, context)
        except PermissionDeniedError as e:
            logger.warning("OpenAI permission: %s", e)
            raise HTTPException(
                status_code=502,
                detail="Сервис ИИ недоступен в вашем регионе или для этого ключа. Проверьте настройки OpenAI.",
            ) from e
        except APIError as e:
            logger.warning("OpenAI API error: %s", e)
            raise HTTPException(status_code=502, detail=str(e.message or str(e))) from e

        add_line(db, sid, "assistant", answer)
        return _with_notice({"answer": answer, "session_id": sid, "operator_active": False})
    finally:
        db.close()


@router.get("/chat/operator-poll")
def operator_poll(
    response: Response,
    session_id: str,
    after_op_seq: int = 0,
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "private, no-store, max-age=0, must-revalidate"
    if not session_id or len(session_id) > 40:
        raise HTTPException(status_code=400, detail="Некорректный session_id")
    db = SessionLocal()
    try:
        bridge = db.get(ChatBridgeSession, session_id)
        if bridge is None:
            raise HTTPException(status_code=404, detail="Сессия не найдена")
        visitor_notice: str | None = None
        if bridge.closure_pending_message:
            visitor_notice = bridge.closure_pending_message
            bridge.closure_pending_message = None
            db.add(bridge)
            db.commit()
        msgs = list_operator_messages_after(db, session_id, after_op_seq)
        return {
            "session_id": session_id,
            "operator_active": bridge.mode == "operator",
            "messages": msgs,
            "visitor_notice": visitor_notice,
        }
    finally:
        db.close()


@router.get("/telegram/webhook")
def telegram_webhook_probe() -> dict[str, str]:
    """Проверка из браузера / curl GET: маршрут доступен. Telegram шлёт только POST."""
    secret_ok = bool(_telegram_webhook_secret_live())
    return {
        "status": "ok",
        "path": "/api/telegram/webhook",
        "env_file": str(BASE_DIR / ".env"),
        "secret_configured": "yes" if secret_ok else "no",
        "hint": "Если secret_configured=no — сохраните .env на диск и перезапустите uvicorn. POST с заголовком X-Telegram-Bot-Api-Secret-Token.",
    }


@router.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> dict[str, str]:
    secret = _telegram_webhook_secret_live()
    if not secret:
        logger.warning(
            "Telegram webhook: TELEGRAM_WEBHOOK_SECRET пустой после load_dotenv(%s). Сохраните .env или проверьте имя переменной.",
            BASE_DIR / ".env",
        )
        raise HTTPException(status_code=503, detail="Webhook не настроен (TELEGRAM_WEBHOOK_SECRET)")
    token_hdr = request.headers.get("X-Telegram-Bot-Api-Secret-Token") or ""
    if token_hdr != secret:
        raise HTTPException(status_code=403, detail="Неверный секрет")

    try:
        update = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    msg = update.get("message") or update.get("edited_message")
    if not isinstance(msg, dict):
        return {"ok": "true"}

    if msg.get("from", {}).get("is_bot"):
        return {"ok": "true"}

    text = (msg.get("text") or msg.get("caption") or "").strip()
    if not text:
        return {"ok": "true"}

    chat = msg.get("chat") or {}
    if not telegram_chat_matches_config(chat.get("id"), Config.TELEGRAM_CHAT_ID):
        logger.warning(
            "Telegram webhook: chat_id=%s не совпадает с TELEGRAM_CHAT_ID из .env (как строка: %r). "
            "Проверьте id чата/группы.",
            chat.get("id"),
            (Config.TELEGRAM_CHAT_ID or "").strip(),
        )
        return {"ok": "true"}

    reply_to = msg.get("reply_to_message")
    db = SessionLocal()
    try:
        session_id: str | None = None
        if isinstance(reply_to, dict):
            session_id = resolve_session_from_reply_chain(db, reply_to)
        if not session_id:
            session_id = resolve_session_from_plain_text(db, text)
        if not session_id:
            rmid = reply_to.get("message_id") if isinstance(reply_to, dict) else None
            logger.info(
                "Telegram webhook: сессия не определена (reply_to message_id=%s, в тексте нет session/UUID "
                "активной сессии operator). Нужен «Ответить» на сообщение бота или строка session: <uuid> из уведомления.",
                rmid,
            )
            return {"ok": "true"}
        bridge_row = db.get(ChatBridgeSession, session_id)
        if bridge_row is None:
            logger.warning(
                "Telegram webhook: сессия %s не найдена в БД (опечатка session в тексте?)",
                session_id,
            )
            return {"ok": "true"}
        if bridge_row.mode != "operator":
            logger.warning(
                "Telegram webhook: сессия %s не в режиме operator (mode=%s), ответ не сохранён",
                session_id,
                bridge_row.mode,
            )
            return {"ok": "true"}
        close_extra = parse_operator_close_command(text)
        if close_extra is not None:
            notice = close_extra if close_extra else Config.OPERATOR_CHAT_CLOSURE_MESSAGE
            try:
                close_session_by_operator(db, session_id, notice)
                add_line(db, session_id, "assistant", notice)
            except Exception as e:
                logger.exception(
                    "Telegram webhook: ошибка при закрытии сессии оператором (session=%s): %s",
                    session_id,
                    e,
                )
                raise HTTPException(status_code=500, detail="database_error") from e
            logger.info("Telegram webhook: оператор закрыл сессию %s", session_id)
            return {"ok": "true"}
        try:
            saved = append_operator_message(db, session_id, text)
        except Exception as e:
            logger.exception(
                "Telegram webhook: ошибка БД при сохранении ответа оператора (session=%s): %s",
                session_id,
                e,
            )
            raise HTTPException(status_code=500, detail="database_error") from e
        if saved is None:
            logger.info(
                "Telegram webhook: после удаления session/UUID текст пуст, в виджет не пишем (session=%s)",
                session_id,
            )
        else:
            logger.info(
                "Telegram webhook: сообщение оператора сохранено, session=%s, line_id=%s, op_seq=%s",
                session_id,
                saved[0],
                saved[1],
            )
    finally:
        db.close()

    return {"ok": "true"}


@router.get("/health")
def rag_health() -> dict[str, Any]:
    has_key = bool(openai_api_key())
    has_index = _index is not None and _metadata is not None
    return {
        "ok": bool(_client and has_index),
        "index": has_index,
        "openai_configured": has_key,
        "openai_client": _client is not None,
        "rag_data_dir": str(RAG_DATA_DIR),
    }
