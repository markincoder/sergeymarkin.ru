# Сайт Сергея Маркина — FastAPI

Веб-приложение: главная с hero и блоком «О сайте», три примера работ (как в `profile.md`), форма обратной связи (SQLite), админ-панель с просмотром заявок, **FAQ-ассистент с RAG** (FAISS + OpenAI) и виджет чата на главной.

За счёт автоматизации ответов на типовые вопросы через ИИ-ассистента можно снизить нагрузку на поддержку и время ответа (ориентир из пилотных внедрений — порядка **25%** быстрее ответ и **~30%** меньше ручных обращений; фактические цифры зависят от тематики и нагрузки).

## Требования

- Python **3.11** (локально и в Docker — см. `Dockerfile`, образ `3.11.x`)
- pip

## Быстрый старт

Из корня проекта (папка с `main.py`):

```bash
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Либо:

```bash
python main.py
```

Сайт: **http://127.0.0.1:8000**

Точка входа ASGI: **`main:app`** (файл `app.py` только реэкспортирует приложение для gunicorn).

## Админ-панель

- URL: **http://127.0.0.1:8000/admin/login**
- Логин по умолчанию: `admin`
- Пароль по умолчанию: `admin123`

**Обязательно** смените учётные данные в продакшене:

```bash
set ADMIN_USERNAME=your_login
set ADMIN_PASSWORD=your_strong_password
set SECRET_KEY=случайная_длинная_строка
```

(Linux/macOS: `export …`)

## Структура проекта

```
├── main.py                 # FastAPI: маршруты, сессии, CSRF, подключение RAG-router
├── app.py                  # Реэкспорт app для gunicorn
├── config.py               # SECRET_KEY, БД, админ, SITE_URL, OPENAI_API_KEY, RAG_DATA_DIR
├── db.py                   # SQLAlchemy engine / сессии
├── models.py               # User, ContactMessage
├── schemas.py              # Pydantic-валидация форм
├── notifications.py      # Почта + Telegram при новой заявке
├── cases_data.py           # Тексты кейсов
├── backend/
│   ├── rag_chat.py         # APIRouter: POST /api/chat, GET /api/health, init_rag()
│   ├── build_index.py      # Построение FAISS из FAQ
│   ├── rag_index.py        # Загрузка индекса и поиск
│   └── rag_data/           # faqs.json, *.txt, faiss_index.bin, faqs_metadata.npy
├── database/
│   └── app.db              # SQLite (создаётся при работе; в Docker — том)
├── templates/              # Jinja2
├── static/
│   ├── css/                # main.css, faq-chat.css
│   ├── js/                 # main.js, faq-chat.js
│   └── images/
└── requirements.txt
```

## FAQ / RAG (как в отдельном FAQ-проекте, но в одном процессе)

### Подготовка окружения для embeddings

В `.env` задайте:

```env
OPENAI_API_KEY=ваш_ключ_openai
```

Ключ читается из `config.py` (переменная окружения или `.env` в корне).

### 1. Данные и построение индекса (FAISS)

- Редактируйте **`backend/rag_data/faqs.json`** — список объектов `{ "question": "...", "answer": "..." }`.
- Дополнительно можно положить **`.txt`** в `backend/rag_data/` (первая непустая строка — заголовок, остальное — текст; см. `backend/build_index.py`).

Сборка индекса из корня проекта:

```bash
python -m backend.build_index
```

Скрипт:

- считает эмбеддинги для текстов «вопрос + ответ» через OpenAI (`text-embedding-3-small`);
- создаёт **`faiss_index.bin`** и **`faqs_metadata.npy`** в `backend/rag_data/`.

В **Docker** том смонтирован на **`/app/database`** (только SQLite); **`backend/rag_data`** целиком из **образа** — после `build_index` закоммитьте бинарники и пересоберите образ.

### 2. API чата (встроено в то же приложение)

Эндпоинты (префикс **`/api`**):

| Метод | Путь | Назначение |
|--------|------|------------|
| `POST` | `/api/chat` | Тело JSON: `{ "message": "текст вопроса" }`. Ответ: `{ "answer": "..." }`. |
| `GET` | `/api/health` | Статус: ключ API и наличие индекса. |

Виджет на главной (`static/js/faq-chat.js`) ходит на **`/api/chat`** того же origin.

### Как это работает (кратко)

1. **Данные FAQ** в `backend/rag_data/` → `build_index.py` строит эмбеддинги и FAISS.
2. **Запрос пользователя** → эмбеддинг запроса → поиск ближайших фрагментов в FAISS.
3. **RAG**: найденный контекст передаётся в промпт к модели чата (OpenAI); ответ возвращается на страницу.

При ошибках провайдера (в т.ч. регион/ключ) API может ответить **502** с полем `detail` — виджет показывает текст ошибки.

## Уведомления о заявках (почта и Telegram)

После сохранения заявки в БД:

1. **Письмо** на адрес из `MAIL_TO` (по умолчанию `sergeymarkin@yandex.ru`) через SMTP.
2. **Сообщение в Telegram** в указанный чат.

Без настроек отправка **тихо пропускается**. Ошибки доставки **не отменяют** успешную отправку формы для пользователя.

Переменные см. `.env.example`:

| Переменная | Назначение |
|------------|------------|
| `MAIL_USERNAME` | Ящик для SMTP |
| `MAIL_PASSWORD` | Пароль приложения (Яндекс / Google и т.д.) |
| `MAIL_TO` | Куда слать письма |
| `TELEGRAM_BOT_TOKEN` | Токен от [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | Числовой id чата |

## Логирование

События (вход в админку, новые заявки, RAG) пишутся в **stdout**.

## Обложка на главной

Положите файл в `static/images/` и в `templates/index.html` укажите имя файла в атрибуте `src` у hero-изображения.

Подробности по серверу и **Traefik**: **[DEPLOY.md](DEPLOY.md)**.

## Безопасность в продакшене

- Задайте `SECRET_KEY`, `ADMIN_PASSWORD` через окружение.
- Для SEO укажите **`SITE_URL`** и при необходимости **`SEO_OG_IMAGE`** — см. `SEO-инструкция.md`.
- Используйте HTTPS и reverse-proxy (Traefik / nginx + gunicorn с uvicorn workers).
- Не храните секреты в коде.

## Docker

Сборка и запуск из каталога с `Dockerfile` (порт **8000**). Типичный сервер: **`docker-compose.yml`** в `~/docker/`, код и **`.env` приложения** в **`~/docker/sergeymarkin/`** — отдельный `~/docker/.env` **не нужен** (пути по умолчанию `./sergeymarkin`). Если весь репозиторий в одной папке с `docker-compose.yml`, в **корневом `.env`** добавьте **`SERGEYMARKIN_APP_DIR=.`** (см. `compose-host.env.example`).

В `docker-compose.yml` том **`sergeymarkin_database`** смонтирован в **`/app/database`** (SQLite). **RAG** — каталог **`backend/rag_data/`** в **образе**. Не используйте **`docker compose down -v`** без бэкапа — ключ `-v` удалит том с БД.

```bash
docker compose build sergeymarkin-web
docker compose up -d sergeymarkin-web
```

Команда в образе: gunicorn с **uvicorn workers**, `main:app`. Подробнее — **[DEPLOY.md](DEPLOY.md)**.
