# FAQ / RAG чат-бот: файлы и перенос в другой проект

## Файлы, относящиеся к функциональности чат-бота

### Сервер (FastAPI)

| Файл | Назначение |
|------|------------|
| `backend/rag_chat.py` | Роутер с префиксом `/api`: `POST /api/chat`, `GET /api/chat/operator-poll`, webhook Telegram `GET|POST /api/telegram/webhook`; инициализация индекса и клиента OpenAI при старте. |
| `backend/rag_index.py` | Загрузка FAISS и поиск `search_similar`. |
| `backend/build_index.py` | Сборка `faiss_index.bin` и `faqs_metadata.npy` из `faq-items.json` и `.txt` в `database/rag_data/`. |
| `backend/operator_bridge.py` | Сессии RAG ↔ оператор, сообщения в Telegram, reply-цепочки, явный handoff к человеку. |
| `backend/chat_intent_patterns.py` | Загрузка регулярок из JSON. |
| `database/rag_data/chat_intent_patterns.json` | Шаблоны для эвристик диалога. |

### Данные RAG

- Каталог **`database/rag_data/`**: исходные тексты (`.txt`), **`faq-items.json`**, сгенерированные **`faiss_index.bin`** и **`faqs_metadata.npy`**.  
  Артефакты индекса можно не копировать: после переноса текстов пересобрать командой `python -m backend.build_index` из корня проекта.

### База данных

| Файл | Назначение |
|------|------------|
| `models.py` | Таблицы `ChatBridgeSession`, `ChatBridgeLine`, `TelegramBridgeMap`. |
| `db.py` | `init_db()` создаёт таблицы; дополнительно — миграции на лету для колонок `closure_pending_message`, `handoff_confirm_pending` на уже существующих SQLite/других БД. |

### Связка с приложением и конфигурация

| Файл | Назначение |
|------|------------|
| `main.py` | `init_rag()` в lifespan, `app.include_router(rag_router)`. |
| `config.py` | `RAG_DATA_DIR`, `OPENAI_API_KEY` (через `backend/openai_key.py`), `CHAT_RAG_THEME_LINE`, `RAG_HANDOFF_L2_MAX`, переменные Telegram (`TELEGRAM_*`), `OPERATOR_CHAT_CLOSURE_MESSAGE`, `SITE_URL` (входит в промпт), `CHAT_API_BASE` и `CORS_ALLOW_ORIGINS` (если фронт и API на разных origin). |
| `backend/openai_key.py` | Чтение `OPENAI_API_KEY` из окружения. |
| `notifications.py` | Функция `send_telegram_bot_message` (остальной модуль — для формы и прочего; при минимальном переносе достаточно вынести отправку в Telegram). |

### Фронтенд виджета

| Файл | Назначение |
|------|------------|
| `templates/base.html` | Разметка виджета (`#chat-launcher`, `#chat-widget`, …) и `window.FAQ_CHAT_API_BASE` из контекста (`main.py` подставляет `Config.CHAT_API_BASE`). |
| `static/js/faq-chat.js` | Запросы к `/api/chat` и `/api/chat/operator-poll` с учётом префикса из `FAQ_CHAT_API_BASE`. |
| `static/css/faq-chat.css` | Стили виджета. |

### Зависимости Python

Из `requirements.txt` для этого блока обычно нужны: `fastapi`, `openai`, `faiss-cpu`, `numpy`, а также то, что уже есть у приложения: `sqlalchemy`, `pydantic`, `python-dotenv`, `requests` (для Telegram).

---

## Как перенести чат-бота в другой проект

1. **Скопировать модули** из `backend/` (перечисленные выше) и поправить импорты под структуру нового проекта (`config`, `db`, `models`, `notifications`).

2. **Перенести модели БД** (`ChatBridgeSession`, `ChatBridgeLine`, `TelegramBridgeMap`) и логику инициализации/миграций из `db.py` — либо интегрировать в ваши миграции (Alembic и т.д.).

3. **Скопировать содержимое `database/rag_data/`** (тексты и `faq-items.json`). Файлы `faiss_index.bin` и `faqs_metadata.npy` можно скопировать или заново сгенерировать: `python -m backend.build_index`.

4. **Подключить в FastAPI**: импорт `init_rag` и `router as rag_router` из `backend.rag_chat`, в lifespan вызвать `init_rag()`, затем `app.include_router(rag_router)`. Убедиться, что пути к `RAG_DATA_DIR` и `.env` соответствуют новому проекту.

5. **Настроить переменные окружения** (см. `config.py` и `.env.example`): как минимум `OPENAI_API_KEY`; при работе оператора через Telegram — токен, chat id, при необходимости `TELEGRAM_WEBHOOK_SECRET`, `TELEGRAM_MESSAGE_THREAD_ID`; тему сайта — `CHAT_RAG_THEME_LINE`; порог эскалации — `RAG_HANDOFF_L2_MAX`; базовый URL сайта — `SITE_URL`.

6. **Фронт**: встроить разметку и подключение CSS/JS как в `base.html`. Если API на другом домене — задать `CHAT_API_BASE` на полный URL бэкенда и `CORS_ALLOW_ORIGINS` на origin страницы с виджетом.

7. **Telegram**: после деплоя настроить `setWebhook` на `https://<хост>/api/telegram/webhook` с секретом `TELEGRAM_WEBHOOK_SECRET`, как ожидает `rag_chat.py`.

8. **Если целевой стек не FastAPI**: сохраните контракт API (`POST` с телом, содержащим `message` и опционально `session_id`; ответ с полями вроде `answer`, `session_id`, флагов оператора) — тогда клиент `faq-chat.js` можно оставить с минимальными правками базового URL.

Подробности поведения (RAG, эскалация, команды оператора) описаны в `README.md` в разделах про FAQ-ассистента и Telegram.
