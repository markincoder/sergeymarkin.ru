# -*- coding: utf-8 -*-
"""RAG чат: APIRouter для FastAPI."""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from openai import APIError, OpenAI, PermissionDeniedError
from pydantic import BaseModel, Field

from config import BASE_DIR, RAG_DATA_DIR

from .openai_key import openai_api_key

from .rag_index import load_index, search_similar

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["rag"])

_index: Any = None
_metadata: Any = None
_client: OpenAI | None = None


def init_rag() -> None:
    """Загрузить индекс и клиент OpenAI (при старте приложения)."""
    global _index, _metadata, _client
    load_dotenv(BASE_DIR / ".env", encoding="utf-8-sig")

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
            "нет FAISS-индекса в backend/rag_data — пересоберите образ после `python -m backend.build_index` "
            "(данные RAG в образе; том только на database/)."
        )
    return "Чат недоступен: " + ("; ".join(parts) if parts else "сервис не инициализирован.")


@router.post("/chat")
def chat_post(body: ChatRequest) -> dict[str, Any]:
    if _client is None or _index is None or _metadata is None:
        raise HTTPException(status_code=503, detail=_rag_unavailable_detail())

    q = body.message.strip()
    try:
        qv = _embed(q)
        hits = search_similar(_index, _metadata, qv, k=3)
        context_parts = []
        for h in hits:
            if isinstance(h, dict):
                context_parts.append(f"Q: {h.get('question', '')}\nA: {h.get('answer', '')}")
            else:
                context_parts.append(str(h))
        context = "\n\n---\n\n".join(context_parts) if context_parts else "(нет контекста)"

        completion = _client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты помощник по сайту Сергея Маркина. Отвечай кратко по-русски, "
                        "опираясь только на переданный контекст. Если в контексте нет ответа, так и скажи."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Контекст:\n{context}\n\nВопрос пользователя:\n{q}",
                },
            ],
            temperature=0.3,
            max_tokens=800,
        )
        answer = (completion.choices[0].message.content or "").strip()
        return {"answer": answer}
    except PermissionDeniedError as e:
        logger.warning("OpenAI permission: %s", e)
        raise HTTPException(
            status_code=502,
            detail="Сервис ИИ недоступен в вашем регионе или для этого ключа. Проверьте настройки OpenAI.",
        ) from e
    except APIError as e:
        logger.warning("OpenAI API error: %s", e)
        raise HTTPException(status_code=502, detail=str(e.message or str(e))) from e


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
