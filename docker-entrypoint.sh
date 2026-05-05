#!/bin/sh
# Без "set -e": при CRLF из репозитория dash выдаёт "set: Illegal option -".
# Том на /app/database перекрывает rag_data из образа — подставляем снимок при первом старте.
RAG_TARGET=/app/database/rag_data
RAG_SEED=/app/_image_rag_data
if [ ! -f "$RAG_TARGET/faq-items.json" ] && [ -f "$RAG_SEED/faq-items.json" ]; then
  echo "docker-entrypoint: копирую RAG-данные из образа в том $RAG_TARGET (нет faq-items.json)."
  mkdir -p "$RAG_TARGET" || exit 1
  cp -a "$RAG_SEED"/. "$RAG_TARGET"/ || exit 1
fi
exec "$@"
