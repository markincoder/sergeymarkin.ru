# Сайт Сергея Маркина — FastAPI

Веб-приложение: главная с hero и блоком «О сайте», **примеры работ** (карточки как в `profile.md`), форма обратной связи (SQLite), админ-панель с просмотром заявок, **FAQ-ассистент с RAG** (FAISS + OpenAI) и виджет чата на главной.

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
│   └── rag_index.py        # Загрузка индекса и поиск
├── database/
│   ├── app.db              # SQLite (создаётся при работе; в Docker — том)
│   └── rag_data/           # faq-items.json, *.txt, faiss_index.bin, faqs_metadata.npy, chat_intent_patterns.json
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

- Редактируйте **`database/rag_data/faq-items.json`** — список объектов `{ "question": "...", "answer": "..." }`.
- Дополнительно можно положить **`.txt`** в `database/rag_data/` (первая непустая строка — заголовок, остальное — текст; см. `backend/build_index.py`).

#### Источники базы знаний (текущий набор)

В поиск и ответ чата попадают **`faq-items.json`** и все **`*.txt`** из этого каталога. Ниже — файлы `.txt`: имя файла удобно как технический идентификатор в метаданных индекса; в промпт уходит заголовок (первая строка файла) и тело.

| Файл | О чём фрагмент |
|------|----------------|
| `about-specialist-and-approach.txt` | Кто такой специалист, направления работы и принципы |
| `homepage-specialization-prompt-vibe.txt` | Как сформулирована специализация на главной (промпты, вайб-кодинг, ценность) |
| `contact-and-communication.txt` | Каналы связи, сопровождение, контакты |
| `how-to-contact-and-what-to-write.txt` | Что написать в первом сообщении, бесплатный/углублённый аудит |
| `chatbots-and-assistants-overview.txt` | Чат-боты и ассистенты: RAG, интеграции, типовые задачи |
| `integrations-and-data-security.txt` | Что нужно от заказчика для интеграций и RAG, безопасность |
| `n8n-automation-patterns.txt` | Автоматизация на n8n, типовые сценарии |
| `pricing-audit-and-payment.txt` | Ориентиры по стоимости, аудит, оплата |
| `timelines-and-project-phases.txt` | Сроки, этапы, удалённая работа, сопровождение |
| `implementation-duration-and-pilots.txt` | Пилоты «2–3 дня» vs реальные сроки сложных проектов |
| `cases-section-and-navigation.txt` | Раздел «Примеры работ» на сайте и как читать кейсы |
| `case-crm-tasks-after-meetings.txt` | Кейс: задачи после созвонов в CRM |
| `case-hr-resume-screening.txt` | Кейс: скрининг резюме для HR |
| `case-telegram-knowledge-support.txt` | Кейс: поддержка в Telegram по базе знаний |
| `case-website-instant-support.txt` | Кейс: ответы посетителям сайта без очереди в поддержку |
| `case-website-knowledge-rag-and-operator-handoff.txt` | Одна линия поддержки, не 24/7; бот по базе знаний на типовые вопросы, иначе — оператор; страница **`/cases/site-support-rag-handoff`** |

**Прочие файлы в `database/rag_data/` (не «знание» для RAG):**

- **`chat_intent_patterns.json`** — регулярные шаблоны для эвристик чата (вопрос / оффтоп / уточнение); в FAISS не индексируется.
- **`faiss_index.bin`**, **`faqs_metadata.npy`** — бинарный индекс и метаданные; создаются командой `python -m backend.build_index`, вручную не редактируются.

Сборка индекса из корня проекта:

```bash
python -m backend.build_index
```

Скрипт:

- считает эмбеддинги для текстов «вопрос + ответ» через OpenAI (`text-embedding-3-small`);
- создаёт **`faiss_index.bin`** и **`faqs_metadata.npy`** в `database/rag_data/`.

В **Docker** том смонтирован на **`/app/database`** (SQLite и **`database/rag_data`** на хосте лежат в этом томе); после `build_index` закоммитьте бинарники и пересоберите образ **или** скопируйте обновлённый `rag_data` в том.

### 2. API чата (встроено в то же приложение)

Эндпоинты (префикс **`/api`**):

| Метод | Путь | Назначение |
|--------|------|------------|
| `POST` | `/api/chat` | JSON: `{ "message": "…", "session_id": "…" }` (session опционально). Ответ: `answer`, `session_id`, `operator_active`. |
| `GET` | `/api/chat/operator-poll` | Query: `session_id`, `after_op_seq` — новые реплики оператора для виджета. |
| `POST` | `/api/telegram/webhook` | Вызывается только Telegram; заголовок `X-Telegram-Bot-Api-Secret-Token`. |
| `GET` | `/api/health` | Статус: ключ API и наличие индекса. |

Виджет на главной (`static/js/faq-chat.js`) ходит на **`/api/chat`** того же origin.

### Как это работает (кратко)

**Обычный ответ (RAG):**

1. **Данные FAQ** в `database/rag_data/` → `build_index.py` строит эмбеддинги и FAISS.
2. **Запрос пользователя** → эмбеддинг запроса → поиск ближайших фрагментов в FAISS.
3. **Ответ модели**: найденный контекст передаётся в промпт к LLM; в виджет возвращается текст ответа (в т.ч. со строкой «Источник: …», если опирались на фрагменты базы).

**Переадресация к оператору (когда и как):**

1. **Явная просьба человека** — пользователь пишет, например, «переведи на оператора», «нужен живой оператор» и т.п. (список фраз в коде, `backend/operator_bridge.py`). Если заданы **`TELEGRAM_BOT_TOKEN`** и **`TELEGRAM_CHAT_ID`**, сервер отправляет в Telegram **историю диалога** и переводит сессию в режим **`operator`**. Пользователь видит подтверждение в виджете.
2. **Нет уверенного ответа в базе** — если лучший фрагмент FAISS «далеко» (порог **`RAG_HANDOFF_L2_MAX`**) и отдельная проверка считает вопрос **по тематике сайта**, бот **не** подключает оператора сразу: предлагает «Подключить оператора? Ответьте «да» или «нет»». После **«да»** (или снова явной просьбы) выполняется тот же сценарий, что в п.1. **«Нет»** возвращает диалог к обычным вопросам без эскалации.
3. **Telegram не настроен** — при срабатывании эскалации пользователь получает сообщение, что оператор недоступен, и подсказку воспользоваться формой обратной связи.

**Диалог с оператором (после подключения):**

- У виджета есть **`session_id`** (хранится в `sessionStorage` браузера): все реплики пользователя в этой сессии попадают в общий транскрипт.
- Пока сессия в режиме оператора, **новые сообщения пользователя** уходят **дублированием в Telegram** (отдельными уведомлениями бота); в виджете на каждую такую отправку приходит короткое подтверждение вроде «Сообщение передано оператору».
- **Ответы оператора** он пишет **в том же чате Telegram** — в идеале **ответом (Reply)** на сообщение бота; запасной вариант — вставить в текст строку **`session:`** и **UUID сессии**, как в уведомлении бота. Сервер принимает webhook от Telegram, сохраняет текст как сообщение оператора.
- Виджет **периодически опрашивает** `GET /api/chat/operator-poll` (порядка раз в 2–3 секунды), пока в ответе **`operator_active: true`**, и показывает новые реплики оператора в окне чата.
- Оператор может завершить обращение командой **`/end`** или **`/закрыть`** (опционально с текстом для посетителя). Сессия снова переводится в режим FAQ; при следующем запросе или опросе пользователь может получить **одноразовое уведомление** (`visitor_notice`), что консультация закрыта.
- Если в браузере **остался старый `session_id`** после прошлой линии с оператором, **короткое приветствие без вопроса** (например «добрый день») может **сбросить** залипший режим оператора и снова включить обычный RAG — подробности см. в `backend/rag_chat.py` и `release_operator_line_to_rag`.

При ошибках провайдера LLM (в т.ч. регион/ключ) API может ответить **502** с полем `detail` — виджет показывает текст ошибки.

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
| `TELEGRAM_CHAT_ID` | Числовой id чата (личка или группа `-100…`) |
| `TELEGRAM_WEBHOOK_SECRET` | Секрет webhook (раздел ниже) |
| `TELEGRAM_MESSAGE_THREAD_ID` | Необязательно: id темы в супергруппе с темами (forum) |

### Telegram: ответы оператора на сайт (webhook)

Уведомления о заявках и эскалация чата в Telegram используют `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID`. Чтобы текст оператора из Telegram попадал в виджет на сайте, Telegram должен вызывать ваш сервер по **публичному HTTPS** — это настраивается через **setWebhook** в Bot API.

**1. В `.env`:**

```env
TELEGRAM_BOT_TOKEN=123456789:AA…ваш_токен…
TELEGRAM_CHAT_ID=-1001234567890
TELEGRAM_WEBHOOK_SECRET=длинная_случайная_строка
```

Придумайте **`TELEGRAM_WEBHOOK_SECRET`** и передайте **то же значение** в `setWebhook` как `secret_token` (шаг 3). После правок `.env` перезапустите приложение.

**2. URL эндпоинта**

Полный путь: **`https://<хост>/api/telegram/webhook`** (тот же домен, что у сайта с чатом).

- Продакшен: например `https://sergeymarkin.ru/api/telegram/webhook`.
- Только локальный ПК: нужен туннель (**ngrok**, **Cloudflare Tunnel**): `https://xxxx.ngrok-free.app/api/telegram/webhook`.

**3. Регистрация webhook**

Пример для **PowerShell** (`^` — перенос строки; в bash уберите `^` и вставьте одну строку):

```bash
curl -s "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook" ^
  -d "url=https://<ВАШ_ХОСТ>/api/telegram/webhook" ^
  -d "secret_token=<TELEGRAM_WEBHOOK_SECRET_как_в_.env>"
```

**4. Проверка**

```bash
curl -s "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getWebhookInfo"
```

Смотрите `url` и при ошибках — `last_error_message`.

**5. Оператор в Telegram**

Удобнее отвечать **Reply** на сообщение бота; запасной вариант — строка `session: <uuid>` из уведомления в тексте ответа. Детали переменных — **`.env.example`**.

Без корректного `setWebhook` или при несовпадении секрета с приложением ответы оператора в виджет **не попадут**.

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

В `docker-compose.yml` том **`sergeymarkin_database`** смонтирован в **`/app/database`** (SQLite и **`rag_data`**). Не используйте **`docker compose down -v`** без бэкапа — ключ `-v` удалит том с БД и RAG.

```bash
docker compose build sergeymarkin-web
docker compose up -d sergeymarkin-web
```

Команда в образе: gunicorn с **uvicorn workers**, `main:app`. Подробнее — **[DEPLOY.md](DEPLOY.md)**.
