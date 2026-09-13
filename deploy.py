# -*- coding: utf-8 -*-
"""Скрипт безопасного деплоя на сервер.

Считывает параметры подключения ИСКЛЮЧИТЕЛЬНО из локального файла deploy_secrets.env.
Никакие пароли, токены и ключи не выводятся в терминал и не передаются в сторонние сервисы.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
SECRETS_FILE = BASE_DIR / "deploy_secrets.env"


def load_env_file(path: Path) -> dict[str, str]:
    """Загрузить переменные из .env файла."""
    data = {}
    if not path.exists():
        return data
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip().strip("'\"")
    return data


def main() -> int:
    if not SECRETS_FILE.exists():
        print("=" * 60)
        print("ОШИБКА: Файл deploy_secrets.env не найден!")
        print("=" * 60)
        print("Для безопасного деплоя выполните шаги:")
        print("1. Скопируйте deploy_secrets.env.example в deploy_secrets.env")
        print("2. Откройте deploy_secrets.env в редакторе и укажите:")
        print("   - SERVER_HOST (IP или домен сервера)")
        print("   - SERVER_USER (имя пользователя, например: sergeymarkin)")
        print("   - SERVER_KEY_PATH (путь к SSH ключу) или SERVER_PASSWORD")
        print("   - REMOTE_DIR (каталог проекта, например: /home/sergeymarkin/docker)")
        print("\nФайл deploy_secrets.env добавлен в .gitignore и защищён от попадания в git.")
        return 1

    cfg = load_env_file(SECRETS_FILE)
    host = cfg.get("SERVER_HOST")
    user = cfg.get("SERVER_USER", "sergeymarkin")
    port = int(cfg.get("SERVER_PORT", "22"))
    key_path = cfg.get("SERVER_KEY_PATH")
    password = cfg.get("SERVER_PASSWORD")
    docker_dir = cfg.get("REMOTE_DOCKER_DIR") or cfg.get("REMOTE_DIR", "/home/sergeymarkin/docker")
    project_subdir = cfg.get("REMOTE_PROJECT_SUBDIR", "sergeymarkin")

    if not host or host == "your.server.ip":
        print("ОШИБКА: Укажите корректный SERVER_HOST в deploy_secrets.env")
        return 1

    print(f"[*] Подключение к {user}@{host}:{port}...")

    try:
        import paramiko
    except ImportError:
        print("ОШИБКА: Не установлен paramiko. Выполните: pip install paramiko")
        return 1

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        connect_kwargs = {
            "hostname": host,
            "port": port,
            "username": user,
            "timeout": 15,
        }
        if key_path and os.path.exists(key_path):
            print(f"[*] Используем SSH-ключ: {key_path}")
            connect_kwargs["key_filename"] = key_path
        elif password:
            print("[*] Используем парольную авторизацию...")
            connect_kwargs["password"] = password
        else:
            # Попробовать стандартные ключи ssh agent
            print("[*] Пробуем системные SSH-ключи...")

        client.connect(**connect_kwargs)
        print("[✓] SSH соединение успешно установлено!")
    except Exception as e:
        print(f"[!] Ошибка подключения по SSH: {e}")
        return 1

    # Умный поиск каталога репозитория (подпапка sergeymarkin или текущий docker_dir)
    detect_and_deploy_script = f"""
set -e
DOCKER_DIR="{docker_dir}"
SUBDIR="{project_subdir}"

if [ -d "$DOCKER_DIR/$SUBDIR/.git" ]; then
    GIT_DIR="$DOCKER_DIR/$SUBDIR"
elif [ -d "$DOCKER_DIR/.git" ]; then
    GIT_DIR="$DOCKER_DIR"
elif [ -d "$DOCKER_DIR/sergeymarkin.ru/.git" ]; then
    GIT_DIR="$DOCKER_DIR/sergeymarkin.ru"
else
    echo "ОШИБКА: Каталог Git-репозитория не найден в $DOCKER_DIR/$SUBDIR!"
    exit 1
fi

echo "[*] Каталог Git-репозитория: $GIT_DIR"
echo "[*] Каталог Docker Compose: $DOCKER_DIR"

echo "=== 1. Git pull в $GIT_DIR ==="
cd "$GIT_DIR"
git fetch origin
git status -s
git pull origin main || git pull

echo "=== 2. Сборка Docker-образа sergeymarkin-web ==="
cd "$DOCKER_DIR"
docker compose build sergeymarkin-web

echo "=== 3. Перезапуск контейнера sergeymarkin-web ==="
docker compose up -d sergeymarkin-web

echo "=== 4. Статус контейнера ==="
docker compose ps sergeymarkin-web
"""

    try:
        print(f"\n[>] Запуск процедуры деплоя на сервере...")
        stdin, stdout, stderr = client.exec_command(detect_and_deploy_script)
        
        while not stdout.channel.exit_status_ready():
            if stdout.channel.recv_ready():
                chunk = stdout.channel.recv(4096).decode("utf-8", errors="replace")
                print(chunk, end="", flush=True)
            if stderr.channel.recv_stderr_ready():
                chunk_err = stderr.channel.recv_stderr(4096).decode("utf-8", errors="replace")
                print(chunk_err, end="", flush=True)

        # Вычитать остатки
        remaining_out = stdout.read().decode("utf-8", errors="replace")
        if remaining_out:
            print(remaining_out, end="", flush=True)
        remaining_err = stderr.read().decode("utf-8", errors="replace")
        if remaining_err:
            print(remaining_err, end="", flush=True)

        exit_code = stdout.channel.recv_exit_status()
        if exit_code != 0:
            print(f"\n[!] Деплой прерван из-за ошибки (код {exit_code})")
            return exit_code

        print("\n" + "=" * 60)
        print("[✓] ДЕПЛОЙ УСПЕШНО ЗАВЕРШЁН!")
        print("Контейнер sergeymarkin-web пересобран и перезапущен.")
        print("=" * 60)
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
