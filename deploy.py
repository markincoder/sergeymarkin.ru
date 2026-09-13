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
    remote_dir = cfg.get("REMOTE_DIR", "/home/sergeymarkin/docker")

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

    commands = [
        f"cd {remote_dir} && git status -s",
        f"cd {remote_dir} && git pull",
        f"cd {remote_dir} && docker compose build sergeymarkin-web",
        f"cd {remote_dir} && docker compose up -d sergeymarkin-web",
        f"cd {remote_dir} && docker compose ps sergeymarkin-web",
    ]

    try:
        for cmd in commands:
            print(f"\n[>] Выполнение: {cmd}")
            stdin, stdout, stderr = client.exec_command(cmd)
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            if out.strip():
                print(out.strip())
            if err.strip():
                print(err.strip())
            exit_code = stdout.channel.recv_exit_status()
            if exit_code != 0:
                print(f"[!] Команда завершилась с кодом ошибки {exit_code}")
                # Если git pull не удался или docker compose упал
                if "git pull" in cmd or "docker compose up" in cmd:
                    print("[!] Деплой прерван из-за ошибки.")
                    return exit_code

        print("\n" + "=" * 60)
        print("[✓] ДЕПЛОЙ УСПЕШНО ЗАВЕРШЁН!")
        print("Контейнер sergeymarkin-web пересобран и запущен.")
        print("=" * 60)
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
