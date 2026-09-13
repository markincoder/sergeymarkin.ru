# -*- coding: utf-8 -*-
"""Админ-панель: маршруты авторизации и управления сообщениями обратной связи."""
from __future__ import annotations

import logging
from typing import Callable, Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from db import get_db
from models import ContactMessage, User
from schemas import LoginFormSchema
from backend.spam_protection import add_to_blocklist, get_blocklist, remove_from_blocklist

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


def get_current_admin(db: Session, request: Request) -> User | None:
    """Получение текущего авторизованного администратора из сессии."""
    uid = request.session.get("user_id")
    if not uid:
        return None
    try:
        return db.get(User, int(uid))
    except (ValueError, TypeError):
        return None


def register_admin_routes(
    app_router: APIRouter,
    *,
    tpl_renderer: Callable[..., HTMLResponse],
    csrf_ensure: Callable[[Request], str],
    csrf_check: Callable[[Request, str | None], bool],
    add_flash: Callable[[Request, str, str], None],
) -> None:
    """Регистрация обработчиков административной панели с инъекцией общих веб-хелперов."""

    @app_router.get("/login", response_class=HTMLResponse, name="admin_login")
    def admin_login_get(request: Request, db: Session = Depends(get_db)):
        if get_current_admin(db, request):
            return RedirectResponse(url=str(request.url_for("admin_dashboard")), status_code=303)
        return tpl_renderer(
            request,
            "admin/login.html",
            csrf_token=csrf_ensure(request),
            field_errors={},
            seo_noindex=True,
            seo_title="Вход",
            meta_desc="Служебный вход в панель управления заявками.",
            og_title="Вход в админ-панель",
        )

    @app_router.post("/login", response_class=HTMLResponse)
    def admin_login_post(
        request: Request,
        db: Session = Depends(get_db),
        username: str = Form(""),
        password: str = Form(""),
        remember: str | None = Form(None),
        csrf_token: str = Form(""),
    ):
        if not csrf_check(request, csrf_token):
            add_flash(request, "Ошибка сессии.", "danger")
            return RedirectResponse(url=str(request.url_for("admin_login")), status_code=303)
        rem = remember in ("on", "true", "1", "yes")
        try:
            LoginFormSchema(username=username, password=password, remember=rem)
        except ValidationError:
            return tpl_renderer(
                request,
                "admin/login.html",
                csrf_token=csrf_ensure(request),
                field_errors={"login": ["Неверный логин или пароль."]},
                seo_noindex=True,
                seo_title="Вход",
                meta_desc="Служебный вход.",
                og_title="Вход в админ-панель",
                status_code=422,
            )

        u = db.scalars(select(User).where(User.username == username.strip())).first()
        if u and u.check_password(password):
            request.session["user_id"] = u.id
            logger.info("Вход в админку: %s", u.username)
            return RedirectResponse(url=str(request.url_for("admin_dashboard")), status_code=303)

        logger.warning("Неудачная попытка входа: %s", username)
        return tpl_renderer(
            request,
            "admin/login.html",
            csrf_token=csrf_ensure(request),
            field_errors={"login": ["Неверный логин или пароль."]},
            seo_noindex=True,
            seo_title="Вход",
            meta_desc="Служебный вход.",
            og_title="Вход в админ-панель",
            status_code=401,
        )

    @app_router.get("/logout", name="admin_logout")
    def admin_logout(request: Request, db: Session = Depends(get_db)):
        u = get_current_admin(db, request)
        if u:
            logger.info("Выход из админки: %s", u.username)
        request.session.pop("user_id", None)
        add_flash(request, "Вы вышли из системы.", "info")
        return RedirectResponse(url=str(request.url_for("index")), status_code=303)

    @app_router.get("", response_class=HTMLResponse, name="admin_dashboard")
    @app_router.get("/", response_class=HTMLResponse, include_in_schema=False)
    def admin_dashboard(request: Request, db: Session = Depends(get_db)):
        user = get_current_admin(db, request)
        if not user:
            return RedirectResponse(
                url=str(request.url_for("admin_login")) + "?next=/admin",
                status_code=303,
            )
        messages = db.execute(
            select(ContactMessage).order_by(ContactMessage.created_at.desc())
        ).scalars().all()
        blocklist = get_blocklist()
        blocked_emails = [e.lower() for e in blocklist.get("blocked_emails", [])]
        return tpl_renderer(
            request,
            "admin/dashboard.html",
            csrf_token=csrf_ensure(request),
            messages=messages,
            current_user=user,
            blocked_emails=blocked_emails,
            seo_noindex=True,
            seo_title="Заявки",
            meta_desc="Панель заявок с формы обратной связи.",
            og_title="Заявки — админ",
        )

    @app_router.post("/message/{message_id}/read", name="admin_message_read")
    def admin_message_read(
        request: Request,
        message_id: int,
        db: Session = Depends(get_db),
        csrf_token: str = Form(""),
    ):
        if not get_current_admin(db, request):
            return RedirectResponse(url=str(request.url_for("admin_login")), status_code=303)
        if not csrf_check(request, csrf_token):
            add_flash(request, "Ошибка CSRF. Повторите действие.", "danger")
            return RedirectResponse(url=str(request.url_for("admin_dashboard")), status_code=303)
        msg = db.get(ContactMessage, message_id)
        if msg:
            msg.is_read = True
            db.commit()
            logger.info("Заявка %s отмечена прочитанной", message_id)
            add_flash(request, "Заявка отмечена как прочитанная.", "success")
        else:
            add_flash(request, "Заявка не найдена.", "warning")
        return RedirectResponse(url=str(request.url_for("admin_dashboard")), status_code=303)

    @app_router.post("/message/{message_id}/unread", name="admin_message_unread")
    def admin_message_unread(
        request: Request,
        message_id: int,
        db: Session = Depends(get_db),
        csrf_token: str = Form(""),
    ):
        if not get_current_admin(db, request):
            return RedirectResponse(url=str(request.url_for("admin_login")), status_code=303)
        if not csrf_check(request, csrf_token):
            add_flash(request, "Ошибка CSRF.", "danger")
            return RedirectResponse(url=str(request.url_for("admin_dashboard")), status_code=303)
        msg = db.get(ContactMessage, message_id)
        if msg:
            msg.is_read = False
            db.commit()
            logger.info("Заявка %s отмечена непрочитанной", message_id)
        return RedirectResponse(url=str(request.url_for("admin_dashboard")), status_code=303)

    @app_router.post("/message/{message_id}/spam", name="admin_message_spam")
    def admin_message_spam(
        request: Request,
        message_id: int,
        db: Session = Depends(get_db),
        csrf_token: str = Form(""),
    ):
        if not get_current_admin(db, request):
            return RedirectResponse(url=str(request.url_for("admin_login")), status_code=303)
        if not csrf_check(request, csrf_token):
            add_flash(request, "Ошибка CSRF.", "danger")
            return RedirectResponse(url=str(request.url_for("admin_dashboard")), status_code=303)
        msg = db.get(ContactMessage, message_id)
        if msg:
            clean_email = msg.email.strip().lower()
            add_to_blocklist(email=clean_email)
            msg.is_read = True
            db.commit()
            logger.warning("Email %s добавлен в спам-лист через админку (заявка #%s)", clean_email, message_id)
            add_flash(request, f"Адрес {clean_email} добавлен в чёрный список спама. Заявки и уведомления с этого адреса заблокированы.", "warning")
        else:
            add_flash(request, "Заявка не найдена.", "warning")
        return RedirectResponse(url=str(request.url_for("admin_dashboard")), status_code=303)

    @app_router.post("/message/{message_id}/delete", name="admin_message_delete")
    def admin_message_delete(
        request: Request,
        message_id: int,
        db: Session = Depends(get_db),
        csrf_token: str = Form(""),
    ):
        if not get_current_admin(db, request):
            return RedirectResponse(url=str(request.url_for("admin_login")), status_code=303)
        if not csrf_check(request, csrf_token):
            add_flash(request, "Ошибка CSRF.", "danger")
            return RedirectResponse(url=str(request.url_for("admin_dashboard")), status_code=303)
        msg = db.get(ContactMessage, message_id)
        if msg:
            db.delete(msg)
            db.commit()
            logger.info("Заявка %s удалена", message_id)
            add_flash(request, "Заявка удалена.", "info")
        return RedirectResponse(url=str(request.url_for("admin_dashboard")), status_code=303)

    @app_router.post("/blocklist/remove", name="admin_blocklist_remove")
    def admin_blocklist_remove(
        request: Request,
        db: Session = Depends(get_db),
        email: str = Form(""),
        csrf_token: str = Form(""),
    ):
        if not get_current_admin(db, request):
            return RedirectResponse(url=str(request.url_for("admin_login")), status_code=303)
        if not csrf_check(request, csrf_token):
            add_flash(request, "Ошибка CSRF.", "danger")
            return RedirectResponse(url=str(request.url_for("admin_dashboard")), status_code=303)
        clean_email = email.strip().lower()
        if clean_email:
            remove_from_blocklist(email=clean_email)
            logger.info("Email %s удалён из спам-листа через админку", clean_email)
            add_flash(request, f"Адрес {clean_email} удалён из спам-листа.", "info")
        return RedirectResponse(url=str(request.url_for("admin_dashboard")), status_code=303)

    @app_router.post("/blocklist/add", name="admin_blocklist_add")
    def admin_blocklist_add(
        request: Request,
        db: Session = Depends(get_db),
        email: str = Form(""),
        csrf_token: str = Form(""),
    ):
        if not get_current_admin(db, request):
            return RedirectResponse(url=str(request.url_for("admin_login")), status_code=303)
        if not csrf_check(request, csrf_token):
            add_flash(request, "Ошибка CSRF.", "danger")
            return RedirectResponse(url=str(request.url_for("admin_dashboard")), status_code=303)
        clean_email = email.strip().lower()
        if clean_email and "@" in clean_email:
            add_to_blocklist(email=clean_email)
            logger.info("Email %s вручную добавлен в спам-лист через админку", clean_email)
            add_flash(request, f"Адрес {clean_email} добавлен в чёрный список спама.", "success")
        else:
            add_flash(request, "Укажите корректный адрес email для блокировки.", "danger")
        return RedirectResponse(url=str(request.url_for("admin_dashboard")), status_code=303)
