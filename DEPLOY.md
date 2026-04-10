# Развёртывание: Ubuntu, пользователь `sergeymarkin`, Docker + Traefik

Путь на сервере: **`/home/sergeymarkin/docker/`** — здесь лежит `docker-compose.yml`, рядом папка **`sergeymarkin/`** (раньше статика + nginx).

Цель: вместо контейнера **`sergeymarkin-nginx`** запускать **Flask + Gunicorn** в Docker с теми же labels Traefik (`sergeymarkin.ru`, TLS, `mytlschallenge`).

---

## Шаг 0. Что будет в итоге

- Старый сервис **`sergeymarkin-nginx`** удаляется из `docker-compose.yml` (иначе два роутера на один `Host` — конфликт).
- Добавляется сервис **`sergeymarkin-web`** (`build: ./sergeymarkin`), порт внутри контейнера **8000**, Traefik как у остальных сайтов.
- Файл **`nginx/sergeymarkin.conf`** для этого домена больше не используется (можно оставить на диске или удалить).
- Код сайта — в **`/home/sergeymarkin/docker/sergeymarkin/`** (весь репозиторий Flask + `Dockerfile`).

---

## Шаг 1. Резервная копия старого сайта

На сервере под пользователем `sergeymarkin`:

```bash
cd /home/sergeymarkin/docker
cp -a sergeymarkin sergeymarkin.backup.$(date +%Y%m%d)
```

---

## Шаг 2. Залить новый код в `sergeymarkin/`

**Вариант A — git** (если репозиторий уже на GitHub/GitLab):

```bash
cd /home/sergeymarkin/docker
rm -rf sergeymarkin
git clone <URL_вашего_репозитория> sergeymarkin
cd sergeymarkin
```

**Вариант B — с вашего ПК (rsync/scp)** — скопируйте **содержимое** проекта (где есть `app.py`, `Dockerfile`, `requirements.txt`) в:

```text
/home/sergeymarkin/docker/sergeymarkin/
```

Проверка:

```bash
ls -la /home/sergeymarkin/docker/sergeymarkin/app.py /home/sergeymarkin/docker/sergeymarkin/Dockerfile
```

---

## Шаг 3. Права и файл `.env`

```bash
cd /home/sergeymarkin/docker/sergeymarkin
chown -R sergeymarkin:sergeymarkin .
chmod 755 .
```

Создайте **`.env`** (секреты не коммитьте):

```bash
cp .env.example .env
nano .env
```

Обязательно для продакшена:

| Переменная | Пример |
|------------|--------|
| `SECRET_KEY` | длинная случайная строка |
| `SITE_URL` | `https://sergeymarkin.ru` |
| `MAIL_*`, `TELEGRAM_*` | по необходимости |

Папка под SQLite (создастся при первом запуске):

```bash
mkdir -p database
chmod 775 database
```

---

## Шаг 4. Правка `docker-compose.yml`

Откройте файл:

```bash
nano /home/sergeymarkin/docker/docker-compose.yml
```

### 4.1. Удалить блок `sergeymarkin-nginx` целиком

Удалите сервис с **`container_name: sergeymarkin-nginx`** (строки с `sergeymarkin-nginx`, volumes на `./sergeymarkin` для nginx и `./nginx/sergeymarkin.conf`).

### 4.2. Вставить новый сервис `sergeymarkin-web`

В том же месте (в секции после Pletelnya / перед WordPress) вставьте:

```yaml
  # ================= Sergeymarkin (Flask) =================
  sergeymarkin-web:
    build: ./sergeymarkin
    image: sergeymarkin-web:local
    container_name: sergeymarkin-web
    restart: unless-stopped
    env_file:
      - ./sergeymarkin/.env
    environment:
      SITE_URL: https://sergeymarkin.ru
    volumes:
      - ./sergeymarkin/database:/app/database
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.sergeymarkin.rule=Host(`sergeymarkin.ru`) || Host(`www.sergeymarkin.ru`)"
      - "traefik.http.routers.sergeymarkin.entrypoints=websecure"
      - "traefik.http.routers.sergeymarkin.tls=true"
      - "traefik.http.routers.sergeymarkin.tls.certresolver=mytlschallenge"
      - "traefik.http.services.sergeymarkin.loadbalancer.server.port=8000"
    networks:
      - web
```

Имя роутера **`sergeymarkin`** совпадает с тем, что было у nginx — Traefik продолжит выдавать сертификат для того же хоста.

Сохраните файл.

---

## Шаг 5. Сборка и запуск

```bash
cd /home/sergeymarkin/docker
docker compose build sergeymarkin-web
docker compose up -d sergeymarkin-web
```

Если старый nginx ещё был запущен, сначала остановите и удалите его контейнер:

```bash
docker compose stop sergeymarkin-nginx 2>/dev/null || true
docker compose rm -f sergeymarkin-nginx 2>/dev/null || true
```

Полная перезагрузка стека (по желанию):

```bash
docker compose up -d
```

---

## Шаг 6. Проверка

```bash
docker logs -f sergeymarkin-web --tail 50
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1/   # с хоста напрямую не сработает — Traefik слушает 80/443
curl -sI https://sergeymarkin.ru
```

В браузере: главная, `/contact`, `/cases`. Админка: `/admin` (смените пароль по умолчанию).

---

## Автозапуск

У Docker Compose с **`restart: unless-stopped`** контейнер поднимается после перезагрузки сервера, если включён сам Docker:

```bash
sudo systemctl enable docker
sudo systemctl status docker
```

Отдельный systemd для Gunicorn **не нужен** — всё в контейнере.

---

## Обновление сайта после правок в коде

```bash
cd /home/sergeymarkin/docker/sergeymarkin
# git pull или rsync новых файлов
cd /home/sergeymarkin/docker
docker compose build sergeymarkin-web
docker compose up -d sergeymarkin-web
```

База **`database/app.db`** лежит на хосте в `./sergeymarkin/database` — при пересборке образа **не теряется**.

---

## Частые проблемы

| Симптом | Что сделать |
|--------|-------------|
| 502 Bad Gateway | `docker logs sergeymarkin-web` — упал Gunicorn; проверьте `.env`, `SECRET_KEY`. |
| Два роутера на один домен | Убедитесь, что **`sergeymarkin-nginx` удалён** из compose и контейнер не создан (`docker ps -a`). |
| Нет прав на БД | `chmod 775 database`, владелец каталога — тот же uid, что в контейнере (часто root в образе — volume на хосте должен быть записываемым). При ошибке SQLite: `chmod 777 database` временно для проверки. |
| Сертификат | Имена `entrypoints`, `certresolver` должны совпадать с Traefik (`websecure`, `mytlschallenge`). |

---

## Файл для справки: фрагмент только сервиса (diff)

Добавлено в репозитории: **`Dockerfile`**, **`.dockerignore`** в корне проекта — они должны лежать в **`sergeymarkin/`** на сервере рядом с `app.py`.


Обновление.
1. сокпировать файлы
2. Запустить
cd /home/sergeymarkin/docker
docker compose build sergeymarkin-web
docker compose up -d sergeymarkin-web
