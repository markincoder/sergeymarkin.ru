# Развёртывание: Ubuntu, Docker + Traefik, сайт sergeymarkin.ru

Приложение — **FastAPI** (ASGI: **gunicorn** + **uvicorn workers**), внутри контейнера порт **8000**, наружу выходит через **Traefik** (HTTPS, тот же `Host`, что раньше у nginx).

Цель: один сервис **`sergeymarkin-web`** вместо отдельного **`sergeymarkin-nginx`** для этого домена (два роутера на один `Host` давали бы конфликт).

---

## Два варианта расположения файлов

В репозитории **`docker-compose.yml` лежит в корне** вместе с `main.py`, `Dockerfile`. На сервере возможны схемы:

| Вариант | Где `docker-compose.yml` | Где код и `.env` | Данные сайта |
|--------|---------------------------|------------------|--------------|
| **A (рекомендуется)** | `/home/sergeymarkin/docker/` | Там же — весь клон репозитория | Том **`sergeymarkin_database`** → **`/app/database`** (SQLite). **RAG** — в образе (`backend/rag_data/`). |
| **B (часто на сервере)** | `/home/sergeymarkin/docker/docker-compose.yml` | Подпапка **`sergeymarkin/`** (`Dockerfile`, **`.env` приложения**) | То же; в `docker-compose.yml` по умолчанию **`./sergeymarkin`** — отдельный **`~/docker/.env` не обязателен**. |

Дальше по шагам — **вариант A** = один каталог с репозиторием, **B** = `~/docker` + `~/docker/sergeymarkin/`.

---

## Шаг 0. Что будет в итоге

- Сервис **`sergeymarkin-nginx`** для `sergeymarkin.ru` **не используется** (удалён из compose, иначе дублирование роутера).
- Сервис **`sergeymarkin-web`**: сборка из **`./`** (рядом с compose), Traefik labels без изменений по смыслу (`sergeymarkin.ru`, TLS, `mytlschallenge`).
- Конфиг **`nginx/sergeymarkin.conf`** для этого сайта не нужен (можно удалить или оставить архивом).

---

## Шаг 1. Резервная копия

```bash
cd /home/sergeymarkin/docker
cp -a . ../docker.backup.$(date +%Y%m%d)
# или только каталог с сайтом: cp -a sergeymarkin sergeymarkin.backup.$(date +%Y%m%d)  # для схемы B
```

---

## Шаг 2. Залить код

Если **`/home/sergeymarkin/docker`** уже клон репозитория с `docker-compose.yml` в корне:

```bash
cd /home/sergeymarkin/docker
git pull
```

Первый раз (корень репозитория = этот каталог):

```bash
cd /home/sergeymarkin
git clone <URL_репозитория> docker
cd /home/sergeymarkin/docker
```

Перед перезаписью каталога сохраните **`.env`**. Данные БД в Docker лежат в volume **`sergeymarkin_database`** (не в папке репозитория) — см. раздел «Бэкап volume» ниже.

**Схема B** (compose в `docker/`, код только в `sergeymarkin/`):

```bash
cd /home/sergeymarkin/docker
git -C sergeymarkin pull || (rm -rf sergeymarkin && git clone <URL> sergeymarkin)
```

Проверка (вариант A):

```bash
ls -la /home/sergeymarkin/docker/main.py /home/sergeymarkin/docker/Dockerfile /home/sergeymarkin/docker/docker-compose.yml
```

---

## Шаг 3. Права и `.env`

```bash
cd /home/sergeymarkin/docker
chown -R sergeymarkin:sergeymarkin .
chmod 755 .
```

**Вариант A** (всё в `docker/`):

```bash
cp .env.example .env
nano .env
```

**Вариант B** (`Dockerfile` и `.env` в `docker/sergeymarkin/`):

```bash
cp sergeymarkin/.env.example sergeymarkin/.env
nano sergeymarkin/.env
```

Отдельный файл **`~/docker/.env` не нужен** — пути в compose по умолчанию указывают на `./sergeymarkin`.

Обязательно для продакшена:

| Переменная | Пример / назначение |
|------------|---------------------|
| `SECRET_KEY` | длинная случайная строка |
| `SITE_URL` | `https://sergeymarkin.ru` (дублируется в compose `environment`, но в приложении читается из env) |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | не оставляйте значения по умолчанию |
| `OPENAI_API_KEY` | для RAG-чата и пересборки индекса (`python -m backend.build_index`) |
| `MAIL_*`, `TELEGRAM_*` | уведомления о заявках — по необходимости |

Локально **без Docker** приложение само создаст **`database/`** и **`database/app.db`**. В **Docker** каталог **`/app/database`** — том **`sergeymarkin_database`** (только SQLite).

При **варианте B** файл `.env` — в **`sergeymarkin/.env`**.

---

## Шаг 4. `docker-compose.yml`

Файл уже в репозитории. Для **варианта A** фрагмент сервиса такой (проверьте, что совпадает):

```yaml
  sergeymarkin-web:
    build:
      context: ${SERGEYMARKIN_APP_DIR:-./sergeymarkin}
      dockerfile: Dockerfile
    env_file:
      - ${SERGEYMARKIN_APP_DIR:-./sergeymarkin}/.env
    volumes:
      - sergeymarkin_database:/app/database
    # ... labels Traefik, port 8000 — см. репозиторий

volumes:
  sergeymarkin_database:
    name: sergeymarkin_database
```

По умолчанию **`SERGEYMARKIN_APP_DIR`** = **`./sergeymarkin`** (схема `~/docker` + `~/docker/sergeymarkin/.env`). Если **`docker-compose.yml` и проект в одной папке**, в **корневом `.env`** задайте **`SERGEYMARKIN_APP_DIR=.`**.

Сеть **`web`** должна существовать: `docker network create web` (если ещё не создана для Traefik).

Удалите из старого compose блок **`sergeymarkin-nginx`**, если он ещё есть.

---

## Шаг 5. Сборка и запуск

```bash
cd /home/sergeymarkin/docker
docker compose build sergeymarkin-web
docker compose up -d sergeymarkin-web
```

Остановка старого nginx этого сайта:

```bash
docker compose stop sergeymarkin-nginx 2>/dev/null || true
docker compose rm -f sergeymarkin-nginx 2>/dev/null || true
```

Перезапуск всего стека при необходимости:

```bash
docker compose up -d
```

---

## Шаг 6. RAG-индекс (перед сборкой образа или после смены FAQ)

Индекс FAISS входит **в образ**. После правок **`backend/rag_data/`** (`faqs.json`, `*.txt`) выполните **в клоне репозитория** (нужен `OPENAI_API_KEY` в окружении или `.env`):

```bash
python -m backend.build_index
```

Закоммитьте **`faiss_index.bin`** и **`faqs_metadata.npy`** вместе с исходниками, затем **`docker compose build`**. В контейнере пересобирать индекс не требуется, если файлы уже в контексте сборки.

---

## Шаг 7. Проверка

```bash
docker logs -f sergeymarkin-web --tail 80
curl -sI https://sergeymarkin.ru
curl -s https://sergeymarkin.ru/api/health
```

В браузере: главная, `/contact`, `/cases`, блок FAQ на главной. Админка: **`/admin/login`** — смените пароль по умолчанию.

Прямой `curl http://127.0.0.1:8000` с хоста сработает только если пробросили порт; обычно доступ только через Traefik на 443.

---

## Данные: именованный volume и бэкап

Имя тома в Docker: **`sergeymarkin_database`** (см. `docker volume ls`). Содержимое **`/app/database`**: **`app.db`** и т.д. Пересборка образа **`docker compose build`** том **не трогает**.

**Бэкап на хост:**

```bash
docker run --rm \
  -v sergeymarkin_database:/data:ro \
  -v "$PWD":/backup \
  alpine tar czf /backup/sergeymarkin-database-$(date +%Y%m%d).tgz -C /data .
```

**Перенос с bind** `./database` на хосте в именованный том:

```bash
docker compose stop sergeymarkin-web
docker run --rm \
  -v /home/sergeymarkin/docker/database:/from:ro \
  -v sergeymarkin_database:/to \
  alpine sh -c 'cp -a /from/. /to/ || true'
docker compose up -d sergeymarkin-web
```

Подставьте свой путь к бывшему каталогу `database` вместо `/home/sergeymarkin/docker/database`.

---

## Обновление сайта после правок в коде

**Вариант A:**

```bash
cd /home/sergeymarkin/docker
git pull
docker compose build sergeymarkin-web
docker compose up -d sergeymarkin-web
```

**Вариант B:**

```bash
cd /home/sergeymarkin/docker/sergeymarkin
git pull
cd /home/sergeymarkin/docker
docker compose build sergeymarkin-web
docker compose up -d sergeymarkin-web
```

База **`app.db`** в volume **`sergeymarkin_database`** (`/app/database/`) при пересборке образа **не теряется**. Удаляется только при **`docker compose down -v`** или `docker volume rm` — делайте бэкап. **RAG** обновляется только с **новым образом** после `build_index` в репозитории.

---

## Автозапуск

При **`restart: unless-stopped`** контейнер поднимается после ребута, если включён Docker:

```bash
sudo systemctl enable docker
sudo systemctl status docker
```

Отдельный unit для приложения **не нужен** — процесс внутри контейнера.

---

## Частые проблемы

| Симптом | Что сделать |
|--------|-------------|
| **502 Bad Gateway** | `docker logs sergeymarkin-web` — падение gunicorn/uvicorn; проверьте `.env`, `SECRET_KEY`, синтаксис. |
| Два роутера на один домен | Убедитесь, что **`sergeymarkin-nginx` удалён** из compose и контейнер не в `docker ps -a`. |
| Нет прав на SQLite | Том: `docker compose exec sergeymarkin-web ls -la /app/database`. |
| Пропали данные после `down` | Команда **`docker compose down -v`** удаляет именованные volumes — не используйте `-v` без бэкапа. |
| RAG не отвечает | В образе есть `backend/rag_data/faiss_index.bin`, `OPENAI_API_KEY`; локально пересоберите индекс и образ; `GET /api/health`. |
| Сертификат | Совпадение `entrypoints=websecure`, `certresolver=mytlschallenge` с Traefik; папка `./traefik` с `acme.json` доступна для записи. |

---

## Краткий чеклист продакшена

- [ ] `.env`: `SECRET_KEY`, сильный `ADMIN_PASSWORD`, при необходимости `OPENAI_API_KEY`, почта/Telegram.
- [ ] Один роутер Traefik на `sergeymarkin.ru` / `www`.
- [ ] HTTPS открывается, форма контактов работает.
- [ ] `/api/health` при необходимости показывает готовность RAG.
- [ ] Пароль админки не дефолтный.
