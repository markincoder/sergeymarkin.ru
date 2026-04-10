# -*- coding: utf-8 -*-
"""
Уведомления о новых заявках: почта (SMTP) и Telegram Bot API.
Ошибки отправки логируются и не ломают ответ пользователю с формы.
"""
from __future__ import annotations

import logging
import smtplib
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage

logger = logging.getLogger(__name__)


def _socket_connect_ipv4(
    host: str,
    port: int,
    timeout: float | None,
    source_address: tuple | None = None,
) -> socket.socket:
    """
    Подключение только по IPv4 (AF_INET).
    Стандартный socket.create_connection может взять AAAA-запись и получить errno 101 без IPv6-маршрута.
    """
    err: OSError | None = None
    for res in socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM):
        af, socktype, proto, _canon, sa = res
        sock: socket.socket | None = None
        try:
            sock = socket.socket(af, socktype, proto)
            sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sa)
            return sock
        except OSError as e:
            err = e
            if sock is not None:
                sock.close()
    if err is not None:
        raise err
    raise OSError(f"Нет IPv4-адреса для {host!r}:{port}")


class SMTP_IPv4(smtplib.SMTP):
    """SMTP с подключением только по IPv4."""

    def _get_socket(self, host, port, timeout):
        if timeout is not None and not timeout:
            raise ValueError("Non-blocking socket (timeout=0) is not supported")
        if self.debuglevel > 0:
            self._print_debug("connect: to", (host, port), self.source_address)
        return _socket_connect_ipv4(host, port, timeout, self.source_address)


class SMTP_SSL_IPv4(smtplib.SMTP_SSL):
    """SMTP_SSL с подключением только по IPv4 (TLS с проверкой имени хоста)."""

    def _get_socket(self, host, port, timeout):
        if self.debuglevel > 0:
            self._print_debug("connect:", (host, port))
        new_socket = _socket_connect_ipv4(host, port, timeout, self.source_address)
        return self.context.wrap_socket(new_socket, server_hostname=self._host)


def _smtp_send_message(
    host: str,
    port: int,
    use_ssl: bool,
    user: str,
    password: str,
    msg: EmailMessage,
    timeout: float,
    force_ipv4: bool,
) -> None:
    """Одна попытка: либо SMTP_SSL (465), либо SMTP + STARTTLS (587)."""
    if use_ssl:
        cls = SMTP_SSL_IPv4 if force_ipv4 else smtplib.SMTP_SSL
        with cls(host, port, timeout=timeout) as smtp:
            smtp.login(user, password)
            smtp.send_message(msg)
    else:
        cls = SMTP_IPv4 if force_ipv4 else smtplib.SMTP
        with cls(host, port, timeout=timeout) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(user, password)
            smtp.send_message(msg)


def _send_email_smtp(app, subject: str, body: str) -> None:
    cfg = app.config
    user = (cfg.get("MAIL_USERNAME") or "").strip()
    password = (cfg.get("MAIL_PASSWORD") or "").strip()
    mail_to = (cfg.get("MAIL_TO") or "").strip()
    timeout = float(cfg.get("MAIL_SMTP_TIMEOUT") or 12)
    force_ipv4 = cfg.get("MAIL_SMTP_FORCE_IPV4", True)

    if not mail_to:
        logger.warning("Почта: не задан MAIL_TO — письмо не отправлено.")
        return
    if not user:
        logger.warning(
            "Почта: не задан MAIL_USERNAME — письмо не отправлено. "
            "Добавьте в .env (и перезапустите приложение)."
        )
        return
    if not password:
        logger.warning(
            "Почта: не задан MAIL_PASSWORD — письмо не отправлено. "
            "Нужен пароль приложения SMTP (Яндекс / Gmail и т.д.), не обычный пароль почты."
        )
        return

    mail_from = (cfg.get("MAIL_FROM") or user).strip()
    host = cfg.get("MAIL_SERVER") or "smtp.yandex.ru"
    port = int(cfg.get("MAIL_PORT") or 465)
    use_ssl = cfg.get("MAIL_USE_SSL", True)
    dual_try = cfg.get("MAIL_SMTP_DUAL_TRY", True)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = mail_to
    msg.set_content(body, charset="utf-8")

    if force_ipv4:
        logger.info("SMTP: используется только IPv4 (MAIL_SMTP_FORCE_IPV4)")

    if dual_try:
        attempts = (
            (587, False, "STARTTLS :587"),
            (465, True, "SSL :465"),
        )
        last_err: Exception | None = None
        for smtp_port, smtp_ssl, label in attempts:
            try:
                logger.info(
                    "SMTP попытка %s %s (→ %s)",
                    label,
                    host,
                    mail_to,
                )
                _smtp_send_message(
                    host,
                    smtp_port,
                    smtp_ssl,
                    user,
                    password,
                    msg,
                    timeout=timeout,
                    force_ipv4=force_ipv4,
                )
                logger.info("Письмо о заявке отправлено на %s", mail_to)
                return
            except (OSError, smtplib.SMTPException) as e:
                last_err = e
                logger.warning("SMTP %s не удалось: %s", label, e)
        if last_err:
            raise last_err
        return

    logger.info(
        "Отправка почты SMTP %s:%s SSL=%s (→ %s)",
        host,
        port,
        use_ssl,
        mail_to,
    )
    _smtp_send_message(
        host, port, use_ssl, user, password, msg, timeout=timeout, force_ipv4=force_ipv4
    )
    logger.info("Письмо о заявке отправлено на %s", mail_to)


def _send_telegram(app, text: str) -> None:
    token = (app.config.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (app.config.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        logger.debug("Telegram не настроен (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID). Пропуск.")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=utf-8")
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read()
    logger.info("Telegram-уведомление отправлено (chat_id=%s)", chat_id)
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("Telegram API ответ: %s", raw[:500])


def notify_new_contact(app, message) -> None:
    """
    Отправить письмо и сообщение в Telegram по модели ContactMessage.
    """
    site = (app.config.get("SITE_URL") or "").rstrip("/") or "—"
    body_lines = [
        "Новая заявка с сайта",
        "",
        f"Имя: {message.name}",
        f"Email: {message.email}",
        f"Телефон: {message.phone}",
        f"Тема: {message.subject}",
        "",
    ]
    if message.body:
        body_lines.append("Сообщение:")
        body_lines.append(message.body)
        body_lines.append("")
    body_lines.append(f"ID в базе: {message.id}")
    body_lines.append(f"Сайт: {site}")
    body_plain = "\n".join(body_lines)

    subject = f"[Сайт] Заявка: {message.subject[:80]}"

    # HTML для Telegram (экранирование)
    def esc(s: str) -> str:
        return (
            (s or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    tg_html = (
        "<b>Новая заявка с сайта</b>\n\n"
        f"👤 {esc(message.name)}\n"
        f"✉️ {esc(message.email)}\n"
        f"📞 {esc(message.phone)}\n"
        f"📌 {esc(message.subject)}\n"
    )
    if message.body:
        tg_html += f"\n{esc(message.body)}\n"
    tg_html += f"\n<code>id={message.id}</code> · {esc(site)}"

    try:
        _send_email_smtp(app, subject, body_plain)
    except smtplib.SMTPAuthenticationError as e:
        app.logger.error(
            "SMTP: ошибка авторизации (проверьте логин и пароль приложения для SMTP): %s",
            e,
        )
    except OSError:
        app.logger.exception(
            "SMTP: ошибка сети (errno 101 часто = нет IPv6; включён принудительный IPv4). "
            "Если снова падает — хостер может резать исходящие 25/465/587. id заявки=%s",
            message.id,
        )
    except Exception:
        app.logger.exception("Не удалось отправить письмо о заявке id=%s", message.id)

    try:
        _send_telegram(app, tg_html)
    except urllib.error.HTTPError as e:
        app.logger.error(
            "Telegram HTTP %s: %s", e.code, e.read()[:500] if e.fp else ""
        )
    except Exception:
        app.logger.exception("Не удалось отправить Telegram о заявке id=%s", message.id)
