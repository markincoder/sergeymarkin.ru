# -*- coding: utf-8 -*-
"""RAG чат: APIRouter для FastAPI."""
from __future__ import annotations

import hmac
import logging
import os
import re
import unicodedata
from typing import Any

import numpy as np
import requests
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
    register_reply_branch_for_session,
    release_operator_line_to_rag,
    resolve_operator_session_from_telegram_message,
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


def _secret_matches(got: str, expected: str) -> bool:
    if not got or not expected:
        return False
    a, b = got.encode("utf-8"), expected.encode("utf-8")
    if len(a) != len(b):
        return False
    return hmac.compare_digest(a, b)


def _telegram_webhook_authorized(request: Request) -> bool:
    """Секрет из заголовка Telegram или ?secret= — заголовок часто срезает прокси."""
    secret = _telegram_webhook_secret_live()
    if not secret:
        return False
    hdr = (
        request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        or request.headers.get("x-telegram-bot-api-secret-token")
        or ""
    )
    query = (request.query_params.get("secret") or "").strip()
    return _secret_matches(hdr, secret) or _secret_matches(query, secret)


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
        "Никогда не добавляй в ответ ссылки на источники, названия файлов или строку вида «Источник: ...»."
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
    raw = (completion.choices[0].message.content or "").strip()
    # Гарантированно вырезаем любые упоминания источников из ответа
    cleaned = re.sub(r"(?im)^\s*источник[и]?\s*:\s*.*$", "", raw).strip()
    cleaned = re.sub(r"(?im)\[?источник[и]?\s*:\s*[^\]\n]+\]?", "", cleaned).strip()
    return cleaned


def _is_unsure_answer(answer_text: str, is_weak: bool) -> bool:
    """Определяет, не уверен ли бот в ответе (для показа кнопки 'Менеджер')."""
    if is_weak:
        return True
    t = (answer_text or "").lower()
    markers = (
        "нет точного ответа",
        "нет информации",
        "нет данных",
        "не содержит информации",
        "не могу ответить",
        "не уверен",
        "не знаю",
        "в базе знаний нет",
        "в материалах сайта нет",
        "не содержится в базе",
        "не найдено в базе",
        "уточните у",
        "связаться через сайт",
        "подключить оператора",
        "свяжитесь напрямую",
    )
    return any(m in t for m in markers)


_OFFER_OPERATOR_AFTER_WEAK_RAG = (
    "В материалах сайта и базе знаний нет точного ответа на ваш вопрос. "
    "Вы можете отправить сообщение напрямую Сергею — нажмите кнопку «Менеджер» ниже или напишите «да»."
)
_HANDOFF_OFFER_DECLINED = (
    "Хорошо. Можете задать другой вопрос по тематике сайта или переформулировать запрос."
)
_OPERATOR_HANDOFF_AFTER_CONFIRM = (
    "Передал вопрос Сергею. Ответ появится здесь; при необходимости уточните детали в этом окне."
)
_OPERATOR_HANDOFF_EXPLICIT_MSG = (
    "Диалог переведён на Сергея. Напишите ваш вопрос в этом окне — сообщение сразу уйдёт напрямую в Telegram. "
    "Также вы можете написать лично в Telegram: @sergeymarkin."
)
_OPERATOR_ACK = "Сообщение передано оператору."
# Явная просьба о человеке, но Telegram не вышел (нет env / ошибка API).
_EXPLICIT_HANDOFF_UNAVAILABLE = (
    "Вы можете отправить сообщение напрямую Сергею в Telegram: @sergeymarkin (https://t.me/sergeymarkin) "
    "или на почту sergeymarkin@yandex.ru, либо заполнить форму «Обратная связь» на сайте."
)
_ALREADY_WITH_OPERATOR = (
    "Диалог уже у оператора — напишите ваш вопрос в этом окне, ответ появится здесь."
)
_OPERATOR_FOLLOWUP_TELEGRAM_FAILED = (
    "Сообщение не удалось доставить в Telegram (нет связи или сбой API). Повторите через минуту "
    "или напишите через форму «Обратная связь» на сайте — режим оператора всё ещё активен."
)
# В режиме operator не использовать _NEUTRAL_REPLY (он звучит как FAQ-бот без оператора).

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
                # На оператора пересылаем все реплики посетителя (не эвристика RAG): иначе короткие
                # «понял», «спасибо», ответы < 12 символов без «?» не уходят в Telegram — создаётся
                # ощущение «переписка оборвалась».
                if _telegram_ready(cfg):
                    forwarded = notify_visitor_message_in_operator_thread(
                        db, sid, q, cfg, send_telegram_bot_message
                    )
                    if forwarded:
                        add_line(db, sid, "assistant", _OPERATOR_ACK)
                        return _with_notice({
                            "answer": _OPERATOR_ACK,
                            "session_id": sid,
                            "operator_active": True,
                        })
                    add_line(db, sid, "assistant", _OPERATOR_FOLLOWUP_TELEGRAM_FAILED)
                    return _with_notice({
                        "answer": _OPERATOR_FOLLOWUP_TELEGRAM_FAILED,
                        "session_id": sid,
                        "operator_active": True,
                    })
                add_line(db, sid, "assistant", _EXPLICIT_HANDOFF_UNAVAILABLE)
                return _with_notice({
                    "answer": _EXPLICIT_HANDOFF_UNAVAILABLE,
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
                        "show_manager_button": True,
                    })

            context = _hits_to_labeled_context(hits)
            answer = _run_rag_answer(q, context)
            show_mgr = _is_unsure_answer(answer, weak)
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
        return _with_notice({
            "answer": answer,
            "session_id": sid,
            "operator_active": False,
            "show_manager_button": show_mgr,
        })
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


def _notify_operator_unrouted_reply(reply_to_message_id: Any) -> None:
    """Сказать оператору в Telegram, что ответ не попал в виджет — иначе Reply выглядит как «ушло»."""
    try:
        mid = int(reply_to_message_id) if reply_to_message_id is not None else None
    except (TypeError, ValueError):
        mid = None
    text = (
        "Ответ не попал в чат на сайте: не удалось привязать его к сессии посетителя.\n\n"
        "Нажмите «Ответить» именно на сообщение бота с историей диалога "
        "(строка session: …) — либо вставьте эту строку в начало ответа."
    )
    try:
        send_telegram_bot_message(get_notify_config(), text=text, reply_to_message_id=mid)
    except Exception:
        logger.exception("Telegram webhook: не удалось отправить подсказку оператору о непривязанном Reply")


def _notify_operator_reply_delivered(reply_to_message_id: Any) -> None:
    try:
        mid = int(reply_to_message_id) if reply_to_message_id is not None else None
    except (TypeError, ValueError):
        mid = None
    try:
        send_telegram_bot_message(
            get_notify_config(),
            text="✓ Сообщение ушло посетителю в чат на сайте.",
            reply_to_message_id=mid,
        )
    except Exception:
        logger.exception("Telegram webhook: не удалось подтвердить доставку ответа оператора")


@router.get("/telegram/webhook")
def telegram_webhook_probe() -> dict[str, Any]:
    """Проверка из браузера / curl GET: маршрут доступен. Telegram шлёт только POST."""
    secret_ok = bool(_telegram_webhook_secret_live())
    out: dict[str, Any] = {
        "status": "ok",
        "path": "/api/telegram/webhook",
        "secret_configured": "yes" if secret_ok else "no",
        "hint": "POST с заголовком X-Telegram-Bot-Api-Secret-Token или ?secret= тот же, что TELEGRAM_WEBHOOK_SECRET. Telegram шлёт только POST.",
    }
    token = (Config.TELEGRAM_BOT_TOKEN or "").strip()
    if token:
        try:
            r = requests.get(f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=12)
            data = (r.json() or {}).get("result") or {}
            out["telegram_webhook_url"] = data.get("url") or ""
            out["pending_update_count"] = data.get("pending_update_count")
            out["last_error_message"] = data.get("last_error_message") or ""
            out["last_error_date"] = data.get("last_error_date")
        except Exception as e:
            out["telegram_webhook_info_error"] = str(e)
    return out


@router.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> dict[str, str]:
    secret = _telegram_webhook_secret_live()
    if not secret:
        logger.warning(
            "Telegram webhook: TELEGRAM_WEBHOOK_SECRET пустой после load_dotenv(%s). Сохраните .env или проверьте имя переменной.",
            BASE_DIR / ".env",
        )
        raise HTTPException(status_code=503, detail="Webhook не настроен (TELEGRAM_WEBHOOK_SECRET)")
    if not _telegram_webhook_authorized(request):
        logger.warning(
            "Telegram webhook: секрет не совпал (заголовок X-Telegram-Bot-Api-Secret-Token или ?secret=). "
            "Прокси мог срезать заголовок — тогда укажите secret в URL setWebhook."
        )
        raise HTTPException(status_code=403, detail="Неверный секрет")

    try:
        update = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    msg = (
        update.get("message")
        or update.get("edited_message")
        or update.get("business_message")
        or update.get("edited_business_message")
    )
    if not isinstance(msg, dict):
        return {"ok": "true"}

    if msg.get("from", {}).get("is_bot"):
        return {"ok": "true"}

    text = (msg.get("text") or msg.get("caption") or "").strip()
    if not text:
        return {"ok": "true"}

    chat = msg.get("chat") or {}
    chat_ok = telegram_chat_matches_config(chat.get("id"), Config.TELEGRAM_CHAT_ID)
    if not chat_ok:
        logger.warning(
            "Telegram webhook: chat_id=%s не совпадает с TELEGRAM_CHAT_ID из .env (как строка: %r). "
            "Проверьте id чата/группы. Попробуем привязать по Reply/session в тексте.",
            chat.get("id"),
            (Config.TELEGRAM_CHAT_ID or "").strip(),
        )

    db = SessionLocal()
    try:
        session_id = resolve_operator_session_from_telegram_message(
            db,
            msg,
            configured_thread_id=Config.TELEGRAM_MESSAGE_THREAD_ID,
            allow_chat_fallback=chat_ok,
        )
        if not session_id:
            rmid = None
            reply_to = msg.get("reply_to_message")
            if isinstance(reply_to, dict):
                rmid = reply_to.get("message_id")
            logger.info(
                "Telegram webhook: сессия не определена (reply_to message_id=%s, chat_ok=%s). "
                "Нужен «Ответить» на сообщение бота с историей или строка session: <uuid>.",
                rmid,
                chat_ok,
            )
            if chat_ok and isinstance(msg.get("reply_to_message"), dict):
                _notify_operator_unrouted_reply(msg.get("message_id"))
            return {"ok": "true"}
        bridge_row = db.get(ChatBridgeSession, session_id)
        if bridge_row is None:
            logger.warning(
                "Telegram webhook: сессия %s не найдена в БД (опечатка session в тексте?)",
                session_id,
            )
            return {"ok": "true"}
        if bridge_row.mode != "operator":
            logger.info(
                "Telegram webhook: сессия %s была в режиме %s — возвращаем operator по ответу из Telegram",
                session_id,
                bridge_row.mode,
            )
            bridge_row.mode = "operator"
            db.add(bridge_row)
            db.commit()
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
        register_reply_branch_for_session(db, msg, session_id)
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
            if chat_ok:
                _notify_operator_reply_delivered(msg.get("message_id"))
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
