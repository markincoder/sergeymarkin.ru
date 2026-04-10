# Сборка: из корня проекта (где лежит app.py)
FROM python:3.11.14-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/database

EXPOSE 8000

# Таймаут запроса выше 30s на случай медленного SMTP (уведомления также уходят в фоне)
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8000", "--timeout", "120", "--graceful-timeout", "30", "app:app"]
