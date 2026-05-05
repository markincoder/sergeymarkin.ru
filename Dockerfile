# Сборка из корня проекта (main.py, app.py)
FROM python:3.11.14-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Снимок rag_data вне тома: при старте entrypoint копирует в /app/database/rag_data, если там ещё нет faq-items.json.
# sed: убираем CR из entrypoint после копирования с Windows — иначе dash: "set: Illegal option -" или сбой shebang.
RUN cp -a /app/database/rag_data /app/_image_rag_data \
    && sed -i 's/\r$//' /app/docker-entrypoint.sh \
    && chmod +x /app/docker-entrypoint.sh

EXPOSE 8000

# Явно через sh: иначе на Windows-репозитории CRLF в скрипте даёт "no such file or directory" при exec.
ENTRYPOINT ["/bin/sh", "/app/docker-entrypoint.sh"]
CMD ["gunicorn", "-w", "2", "-k", "uvicorn.workers.UvicornWorker", "-b", "0.0.0.0:8000", "--timeout", "120", "--graceful-timeout", "30", "main:app"]
