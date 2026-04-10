# Сайт на Flask — Сергей Маркин

Полноценное веб-приложение: главная с hero и блоком «О сайте», три примера работ (как в `profile.md`), форма обратной связи (SQLite), админ-панель с просмотром заявок.

## Требования

- Python **3.11** (локально и в Docker — см. `Dockerfile`, образ `3.11.14`)
- pip

## Быстрый старт (одна команда)

Из корня проекта (папка с `app.py`):

```bash
pip install -r requirements.txt && python app.py
```

(Можно также `python main.py` — то же самое.)

Сайт откроется по адресу **http://127.0.0.1:5000**

Альтернатива через Flask CLI:

```bash
pip install -r requirements.txt
set FLASK_APP=app.py
flask run
```

(Linux/macOS: `export FLASK_APP=app.py`)

## Админ-панель

- URL: **http://127.0.0.1:5000/admin/login**
- Логин по умолчанию: `admin`
- Пароль по умолчанию: `admin123`

**Обязательно** смените пароль в продакшене через переменные окружения:

```bash
set ADMIN_USERNAME=your_login
set ADMIN_PASSWORD=your_strong_password
set SECRET_KEY=случайная_длинная_строка
```

## Структура проекта

```
├── app.py              # Точка входа, маршруты
├── config.py           # Настройки (SECRET_KEY, БД, админ)
├── extensions.py       # db, login_manager
├── models.py           # User, ContactMessage
├── forms.py            # WTForms + валидация + CSRF
├── notifications.py    # Почта + Telegram при новой заявке
├── cases_data.py       # Тексты кейсов
├── database/           # SQLite app.db (создаётся автоматически)
├── templates/          # Jinja2
├── static/
│   ├── css/main.css
│   ├── js/main.js
│   └── images/         # SVG для кейсов и hero
└── requirements.txt
```

## Уведомления о заявках (почта и Telegram)

После сохранения заявки в БД:

1. **Письмо** на `sergeymarkin@yandex.ru` (или адрес из `MAIL_TO`) через SMTP Яндекса.
2. **Сообщение в Telegram** боту в указанный чат (`TELEGRAM_CHAT_ID`).

Без настроек почта и Telegram **тихо пропускаются** (в логе уровня DEBUG). Ошибки отправки **не отменяют** успешную отправку формы для пользователя.

Задайте переменные окружения (см. `.env.example`):

| Переменная | Назначение |
|------------|------------|
| `MAIL_USERNAME` | Ящик Яндекса для входа в SMTP (например `you@yandex.ru`) |
| `MAIL_PASSWORD` | [Пароль приложения](https://yandex.ru/support/id/authorization/app-passwords.html), не основной пароль |
| `MAIL_TO` | Куда слать письма (по умолчанию `sergeymarkin@yandex.ru`) |
| `TELEGRAM_BOT_TOKEN` | Токен от [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | Числовой id чата (напишите своему боту `/start`, затем откройте `https://api.telegram.org/bot<TOKEN>/getUpdates` и найдите `"chat":{"id":...}`) |

Имя пользователя Telegram (`@sergeymarkin`) в API **не подставляется** — нужен именно **числовой** `chat_id` вашего аккаунта с ботом.

## Логирование

Основные события (вход в админку, новые заявки, удаление) пишутся в **stdout** (консоль).

## Замена обложки на главной

Положите файл в `static/images/` (например `hero.jpg`) и в шаблоне `templates/index.html` замените `hero-profile.svg` на имя вашего файла.

Подробная инструкция по серверу Ubuntu и **Traefik** (замена статического `index1.html`): см. **[DEPLOY.md](DEPLOY.md)**.

## Безопасность в продакшене

- Установите `SECRET_KEY`, `ADMIN_PASSWORD` через переменные окружения.
- Для SEO укажите **`SITE_URL`** (канонический домен, например `https://sergeymarkin.ru`) и при необходимости **`SEO_OG_IMAGE`** — см. `SEO-инструкция.md`.
- Используйте HTTPS и reverse-proxy (nginx + gunicorn).
- Не храните пароли в коде.
