# -*- coding: utf-8 -*-
"""FastAPI: публичные страницы, форма, админка, RAG API."""
from __future__ import annotations

import logging
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware
from starlette.templating import Jinja2Templates
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from backend.rag_chat import init_rag, router as rag_router
from cases_data import CASES, get_case_by_slug
from config import Config
from db import SessionLocal, get_db, init_db
from models import ContactMessage, User
from notifications import notify_contact_submission
from schemas import ContactFormSchema, LoginFormSchema

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def get_notify_cfg() -> dict[str, Any]:
    from config import get_notify_config as _gn

    return _gn()


def _enqueue_contact_notifications(message_id: int) -> None:
    cfg = get_notify_cfg()

    def runner() -> None:
        db = SessionLocal()
        try:
            m = db.get(ContactMessage, message_id)
            if m is not None:
                notify_contact_submission(
                    cfg,
                    name=m.name,
                    email=m.email,
                    phone=m.phone,
                    subject=m.subject,
                    body=m.body,
                )
        finally:
            db.close()

    threading.Thread(target=runner, daemon=True).start()


def _ensure_database_dir() -> None:
    (BASE_DIR / "database").mkdir(parents=True, exist_ok=True)


def _seed_admin_if_needed() -> None:
    db = SessionLocal()
    try:
        if db.execute(select(User).limit(1)).scalar_one_or_none():
            return
        u = User(username=Config.ADMIN_USERNAME)
        u.set_password(Config.ADMIN_PASSWORD)
        db.add(u)
        db.commit()
        logger.warning(
            "Создан администратор по умолчанию: логин=%s (смените пароль в продакшене!)",
            u.username,
        )
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _ensure_database_dir()
    init_db()
    _seed_admin_if_needed()
    init_rag()
    yield


app = FastAPI(title="sergeymarkin.ru", lifespan=lifespan)
_cors_origins = [o.strip() for o in (Config.CORS_ALLOW_ORIGINS or "").split(",") if o.strip()]
if _cors_origins:
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
app.add_middleware(SessionMiddleware, secret_key=Config.SECRET_KEY, max_age=14 * 24 * 3600)
# Внешний слой: за Traefik client=172.x, иначе scheme=http и url_for ломает ссылки/CSS.
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.include_router(rag_router)


def _route_name(request: Request) -> str | None:
    r = request.scope.get("route")
    return getattr(r, "name", None) if r else None


def _seo_context(request: Request) -> dict[str, Any]:
    site = Config.SITE_URL.rstrip("/")
    path = request.url.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    canonical = site + path
    og_img = site + (Config.SEO_OG_IMAGE or "/static/images/hero-profile.svg")
    person_ld = {
        "@context": "https://schema.org",
        "@type": "Person",
        "name": "Сергей Маркин",
        "jobTitle": "Prompt Engineer",
        "description": "Промпт-инженер и специалист по AI, вайб-кодинг, автоматизация бизнес-процессов.",
        "url": site + "/",
        "image": og_img,
        "email": "markincoder@gmail.com",
        "telephone": "+7-951-743-16-09",
        "sameAs": ["https://t.me/markin_coder"],
        "knowsAbout": [
            "AI",
            "Prompt Engineering",
            "RAG",
            "n8n",
            "Telegram bots",
            "Notion",
        ],
    }
    return {
        "site_url": site,
        "canonical_url": canonical,
        "seo_og_image": og_img,
        "seo_person_ld": person_ld,
    }


def _flash_list(request: Request) -> list[tuple[str, str]]:
    raw = request.session.pop("flashes", None)
    if not raw:
        return []
    return list(raw)


def _add_flash(request: Request, message: str, category: str = "info") -> None:
    flashes = list(request.session.get("flashes", []))
    flashes.append((category, message))
    request.session["flashes"] = flashes


def _tpl(
    request: Request,
    name: str,
    *,
    status_code: int = 200,
    **kwargs: Any,
) -> HTMLResponse:
    def url_for(__name: str, **path_params: Any) -> str:
        return str(request.url_for(__name, **path_params))

    flashes = _flash_list(request)
    ctx = {
        "request": request,
        "url_for": url_for,
        "route_name": _route_name(request),
        "flash_messages": flashes,
        **_seo_context(request),
        **kwargs,
    }
    if "chat_api_base" not in ctx:
        ctx["chat_api_base"] = Config.CHAT_API_BASE
    return templates.TemplateResponse(name, ctx, status_code=status_code)


def _csrf_ensure(request: Request) -> str:
    import secrets

    tok = request.session.get("csrf_token")
    if not tok:
        tok = secrets.token_urlsafe(32)
        request.session["csrf_token"] = tok
    return tok


def _csrf_check(request: Request, token: str | None) -> bool:
    return bool(token and token == request.session.get("csrf_token"))


def _current_user(db: Session, request: Request) -> User | None:
    uid = request.session.get("user_id")
    if not uid:
        return None
    return db.get(User, int(uid))


@app.get("/", response_class=HTMLResponse, name="index")
def index(request: Request):
    return _tpl(
        request,
        "index.html",
        cases=CASES,
        seo_title="Главная",
        meta_desc=(
            "Трансформирую хаос в алгоритмы. Промпт-инженер, вайб-кодинг, автоматизация до 50% рутины с ИИ. "
            "HR, RAG-боты, n8n, Notion."
        ),
        og_title="Сергей Маркин — Prompt Engineer | ИИ автоматизация",
    )


@app.get("/cases", response_class=HTMLResponse, name="cases_list")
def cases_list(request: Request):
    return _tpl(
        request,
        "cases.html",
        cases=CASES,
        seo_title="Примеры работ",
        meta_desc=(
            "Примеры работ: экономия времени HR на скрининге, поддержка в Telegram по документам, "
            "задачи после созвонов в CRM, быстрые ответы посетителям сайта. Сергей Маркин, prompt engineer."
        ),
        og_title="Примеры работ — Сергей Маркин | AI и автоматизация",
    )


@app.get("/cases/{slug}", response_class=HTMLResponse, name="case_detail")
def case_detail(request: Request, slug: str):
    case = get_case_by_slug(slug)
    if not case:
        raise HTTPException(404)
    site = Config.SITE_URL.rstrip("/")
    og_img_case = site + "/static/images/" + case["image"]
    case_url = site + str(request.url_for("case_detail", slug=case["slug"]))
    breadcrumb_ld = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Главная", "item": site + "/"},
            {
                "@type": "ListItem",
                "position": 2,
                "name": "Примеры работ",
                "item": site + str(request.url_for("cases_list")),
            },
            {"@type": "ListItem", "position": 3, "name": case["title"], "item": case_url},
        ],
    }
    return _tpl(
        request,
        "case_detail.html",
        case=case,
        seo_title=case["title"],
        meta_desc=case["short"],
        og_title=f'{case["title"]} — пример работ | Сергей Маркин',
        og_image=og_img_case,
        breadcrumb_ld=breadcrumb_ld,
    )


@app.get("/contact", response_class=HTMLResponse, name="contact")
def contact_get(request: Request):
    return _tpl(
        request,
        "contact.html",
        csrf_token=_csrf_ensure(request),
        field_errors={},
        form_values={},
        seo_title="Обратная связь",
        meta_desc=(
            "Свяжитесь со мной: форма обратной связи. Обсудим проект, сроки и автоматизацию с ИИ. "
            "Сергей Маркин, prompt engineer."
        ),
        og_title="Обратная связь — Сергей Маркин",
    )


@app.post("/contact", response_class=HTMLResponse)
def contact_post(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    subject: str = Form(""),
    body: str = Form(""),
    csrf_token: str = Form(""),
):
    if not _csrf_check(request, csrf_token):
        _add_flash(request, "Ошибка сессии. Обновите страницу и попробуйте снова.", "danger")
        return RedirectResponse(url=str(request.url_for("contact")), status_code=303)
    try:
        data = ContactFormSchema(
            name=name,
            email=email,
            phone=phone,
            subject=subject,
            body=body or None,
        )
    except ValidationError as e:
        errs: dict[str, list[str]] = {}
        values = {"name": name, "email": email, "phone": phone, "subject": subject, "body": body}
        for err in e.errors():
            loc = err.get("loc", ())
            if loc:
                field = str(loc[0])
                errs.setdefault(field, []).append(str(err.get("msg", "Ошибка")))
        return _tpl(
            request,
            "contact.html",
            csrf_token=_csrf_ensure(request),
            field_errors=errs,
            form_values=values,
            seo_title="Обратная связь",
            meta_desc="Свяжитесь со мной: форма обратной связи.",
            og_title="Обратная связь — Сергей Маркин",
            status_code=422,
        )

    msg = ContactMessage(
        name=data.name,
        email=str(data.email),
        phone=data.phone,
        subject=data.subject,
        body=data.body,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    logger.info("Новая заявка с формы: email=%s subject=%s", msg.email, msg.subject)
    _enqueue_contact_notifications(msg.id)
    _add_flash(request, "Спасибо! Сообщение отправлено. Мы свяжемся с вами.", "success")
    return RedirectResponse(url=str(request.url_for("contact")), status_code=303)


@app.get("/robots.txt", response_class=Response)
def robots_txt(request: Request):
    site = Config.SITE_URL.rstrip("/")
    body = f"""User-agent: *
Allow: /
Disallow: /admin

Sitemap: {site}/sitemap.xml
"""
    return Response(content=body, media_type="text/plain; charset=utf-8")


@app.get("/sitemap.xml", response_class=Response)
def sitemap_xml(request: Request):
    site = Config.SITE_URL.rstrip("/")
    urls = [
        ("", "weekly", "1.0"),
        ("/cases", "weekly", "0.9"),
        ("/contact", "monthly", "0.8"),
    ]
    for c in CASES:
        urls.append((f"/cases/{c['slug']}", "monthly", "0.8"))

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for loc, changefreq, priority in urls:
        lines.append("  <url>")
        lines.append(f"    <loc>{escape(site + loc)}</loc>")
        lines.append(f"    <changefreq>{changefreq}</changefreq>")
        lines.append(f"    <priority>{priority}</priority>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return Response(content="\n".join(lines), media_type="application/xml; charset=utf-8")


@app.get("/admin/login", response_class=HTMLResponse, name="admin_login")
def admin_login_get(request: Request, db: Session = Depends(get_db)):
    if _current_user(db, request):
        return RedirectResponse(url=str(request.url_for("admin_dashboard")), status_code=303)
    return _tpl(
        request,
        "admin/login.html",
        csrf_token=_csrf_ensure(request),
        field_errors={},
        seo_noindex=True,
        seo_title="Вход",
        meta_desc="Служебный вход в панель управления заявками.",
        og_title="Вход в админ-панель",
    )


@app.post("/admin/login", response_class=HTMLResponse)
def admin_login_post(
    request: Request,
    db: Session = Depends(get_db),
    username: str = Form(""),
    password: str = Form(""),
    remember: str | None = Form(None),
    csrf_token: str = Form(""),
):
    if not _csrf_check(request, csrf_token):
        _add_flash(request, "Ошибка сессии.", "danger")
        return RedirectResponse(url=str(request.url_for("admin_login")), status_code=303)
    rem = remember in ("on", "true", "1", "yes")
    try:
        LoginFormSchema(username=username, password=password, remember=rem)
    except ValidationError:
        return _tpl(
            request,
            "admin/login.html",
            csrf_token=_csrf_ensure(request),
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
    return _tpl(
        request,
        "admin/login.html",
        csrf_token=_csrf_ensure(request),
        field_errors={"login": ["Неверный логин или пароль."]},
        seo_noindex=True,
        seo_title="Вход",
        meta_desc="Служебный вход.",
        og_title="Вход в админ-панель",
        status_code=401,
    )


@app.get("/admin/logout", name="admin_logout")
def admin_logout(request: Request, db: Session = Depends(get_db)):
    u = _current_user(db, request)
    if u:
        logger.info("Выход из админки: %s", u.username)
    request.session.pop("user_id", None)
    _add_flash(request, "Вы вышли из системы.", "info")
    return RedirectResponse(url=str(request.url_for("index")), status_code=303)


@app.get("/admin", response_class=HTMLResponse, name="admin_dashboard")
def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    user = _current_user(db, request)
    if not user:
        return RedirectResponse(
            url=str(request.url_for("admin_login")) + "?next=/admin",
            status_code=303,
        )
    messages = db.execute(select(ContactMessage).order_by(ContactMessage.created_at.desc())).scalars().all()
    return _tpl(
        request,
        "admin/dashboard.html",
        csrf_token=_csrf_ensure(request),
        messages=messages,
        current_user=user,
        seo_noindex=True,
        seo_title="Заявки",
        meta_desc="Панель заявок с формы обратной связи.",
        og_title="Заявки — админ",
    )


def _admin_post_guard(request: Request, db: Session) -> User | None:
    user = _current_user(db, request)
    if not user:
        return None
    return user


@app.post("/admin/message/{message_id}/read", name="admin_message_read")
def admin_message_read(
    request: Request,
    message_id: int,
    db: Session = Depends(get_db),
    csrf_token: str = Form(""),
):
    if not _admin_post_guard(request, db):
        return RedirectResponse(url=str(request.url_for("admin_login")), status_code=303)
    if not _csrf_check(request, csrf_token):
        _add_flash(request, "Ошибка CSRF. Повторите действие.", "danger")
        return RedirectResponse(url=str(request.url_for("admin_dashboard")), status_code=303)
    msg = db.get(ContactMessage, message_id)
    if msg:
        msg.is_read = True
        db.commit()
        logger.info("Заявка %s отмечена прочитанной", message_id)
        _add_flash(request, "Заявка отмечена как прочитанная.", "success")
    else:
        _add_flash(request, "Заявка не найдена.", "warning")
    return RedirectResponse(url=str(request.url_for("admin_dashboard")), status_code=303)


@app.post("/admin/message/{message_id}/unread", name="admin_message_unread")
def admin_message_unread(
    request: Request,
    message_id: int,
    db: Session = Depends(get_db),
    csrf_token: str = Form(""),
):
    if not _admin_post_guard(request, db):
        return RedirectResponse(url=str(request.url_for("admin_login")), status_code=303)
    if not _csrf_check(request, csrf_token):
        _add_flash(request, "Ошибка CSRF.", "danger")
        return RedirectResponse(url=str(request.url_for("admin_dashboard")), status_code=303)
    msg = db.get(ContactMessage, message_id)
    if msg:
        msg.is_read = False
        db.commit()
        logger.info("Заявка %s отмечена непрочитанной", message_id)
    return RedirectResponse(url=str(request.url_for("admin_dashboard")), status_code=303)


@app.post("/admin/message/{message_id}/delete", name="admin_message_delete")
def admin_message_delete(
    request: Request,
    message_id: int,
    db: Session = Depends(get_db),
    csrf_token: str = Form(""),
):
    if not _admin_post_guard(request, db):
        return RedirectResponse(url=str(request.url_for("admin_login")), status_code=303)
    if not _csrf_check(request, csrf_token):
        _add_flash(request, "Ошибка CSRF.", "danger")
        return RedirectResponse(url=str(request.url_for("admin_dashboard")), status_code=303)
    msg = db.get(ContactMessage, message_id)
    if msg:
        db.delete(msg)
        db.commit()
        logger.info("Заявка %s удалена", message_id)
        _add_flash(request, "Заявка удалена.", "info")
    return RedirectResponse(url=str(request.url_for("admin_dashboard")), status_code=303)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 404:
        return _tpl(
            request,
            "errors/404.html",
            seo_title="Страница не найдена",
            meta_desc="Страница не найдена. Сергей Маркин — prompt engineer, AI и автоматизация.",
            og_title="404 — страница не найдена",
            seo_noindex=True,
            status_code=404,
        )
    from fastapi.responses import JSONResponse

    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
