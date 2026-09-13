# -*- coding: utf-8 -*-
"""FastAPI: публичные страницы, форма, админка, RAG API."""
from __future__ import annotations

import hmac
import logging
import secrets
import sys
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware
from starlette.templating import Jinja2Templates
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from backend.admin_routes import register_admin_routes, router as admin_router
from backend.captcha_image import normalize_code, random_code, render_png
from backend.rag_chat import init_rag, router as rag_router
from backend.seo import get_seo_context
from backend.spam_protection import check_submission_for_spam
from cases_data import CASES, CATEGORIES, get_case_by_slug, get_related_cases
from config import Config
from db import SessionLocal, get_db, init_db
from models import ContactMessage, User
from notifications import notify_contact_submission
from schemas import ContactFormSchema

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
        **get_seo_context(request),
        **kwargs,
    }
    if "chat_api_base" not in ctx:
        ctx["chat_api_base"] = Config.CHAT_API_BASE
    return templates.TemplateResponse(name, ctx, status_code=status_code)


def _captcha_issue(request: Request) -> str:
    code = random_code()
    request.session["contact_captcha"] = {
        "code": code,
        "exp": time.time() + 15 * 60,
    }
    return code


def _captcha_ok(request: Request, user_answer: str) -> bool:
    if not user_answer:
        # Безбарьерный режим: защита через CSRF + honeypot
        return True
    data = request.session.pop("contact_captcha", None)
    if not data or time.time() > float(data.get("exp") or 0):
        return True
    expected = normalize_code(str(data.get("code") or "")).encode("utf-8")
    got = normalize_code(user_answer).encode("utf-8")
    if not expected or len(expected) != len(got):
        return False
    return hmac.compare_digest(expected, got)


def _contact_page(
    request: Request,
    *,
    status_code: int = 200,
    field_errors: dict[str, list[str]] | None = None,
    form_values: dict[str, str] | None = None,
) -> HTMLResponse:
    _captcha_issue(request)
    return _tpl(
        request,
        "contact.html",
        csrf_token=_csrf_ensure(request),
        field_errors=field_errors or {},
        form_values=form_values or {},
        captcha_bust=secrets.token_urlsafe(8),
        seo_title="Заявка на AI-аудит и контакты",
        meta_desc=(
            "Заказать внедрение искусственного интеллекта, разработку RAG-бота или аудит бизнес-процессов за 24–48 часов. "
            "Свяжитесь напрямую в Telegram @sergeymarkin или отправьте заявку на пилот за 5 дней."
        ),
        og_title="Заказать разработку AI-ассистента или аудит процессов — Сергей Маркин",
        status_code=status_code,
    )


def _csrf_ensure(request: Request) -> str:
    tok = request.session.get("csrf_token")
    if not tok:
        tok = secrets.token_urlsafe(32)
        request.session["csrf_token"] = tok
    return tok


def _csrf_check(request: Request, token: str | None) -> bool:
    return bool(token and token == request.session.get("csrf_token"))


register_admin_routes(
    admin_router,
    tpl_renderer=_tpl,
    csrf_ensure=_csrf_ensure,
    csrf_check=_csrf_check,
    add_flash=_add_flash,
)
app.include_router(admin_router)


@app.get("/", response_class=HTMLResponse, name="index")
def index(request: Request):
    return _tpl(
        request,
        "index.html",
        cases=CASES,
        seo_title="Внедрение AI и автоматизация бизнеса",
        meta_desc=(
            "AI-инженер Сергей Маркин: внедрение нейросетей и автоматизация бизнес-процессов под ключ. "
            "RAG-ассистенты по базам знаний компании, сквозные сценарии n8n, умные Telegram-боты. "
            "Сокращение рутины до 70%, запуск пилота за 5 дней."
        ),
        og_title="Сергей Маркин — Внедрение искусственного интеллекта и автоматизация бизнеса",
    )


@app.get("/cases", response_class=HTMLResponse, name="cases_list")
def cases_list(request: Request):
    return _tpl(
        request,
        "cases.html",
        cases=CASES,
        categories=CATEGORIES,
        seo_title="Кейсы внедрения AI и автоматизации",
        meta_desc=(
            "Реальные кейсы внедрения нейросетей и автоматизации: RAG-боты по базам знаний, сквозные сценарии n8n, "
            "AI-скрининг резюме и аналитика звонков Whisper. Измеримые результаты для бизнеса."
        ),
        og_title="Кейсы внедрения AI и автоматизации бизнес-процессов — Сергей Маркин",
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
        related_cases=get_related_cases(slug, 3),
        seo_title=case["title"],
        meta_desc=case["short"],
        og_title=f'{case["title"]} — пример работ | Сергей Маркин',
        og_image=og_img_case,
        breadcrumb_ld=breadcrumb_ld,
    )


@app.get("/contact", response_class=HTMLResponse, name="contact")
def contact_get(request: Request):
    request.session["contact_opened_at"] = time.time()
    subj = request.query_params.get("subject", "")
    init_vals = {"subject": subj} if subj else None
    return _contact_page(request, form_values=init_vals)


@app.post("/contact", response_class=HTMLResponse)
def contact_post(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    subject: str = Form(""),
    body: str = Form(""),
    captcha: str = Form(""),
    website: str = Form(""),
    csrf_token: str = Form(""),
):
    if not _csrf_check(request, csrf_token):
        _add_flash(request, "Ошибка сессии. Обновите страницу и попробуйте снова.", "danger")
        return RedirectResponse(url=str(request.url_for("contact")), status_code=303)

    # Защита от спама: Honeypot, Timing, Rate-limit, блок-лист ключевых слов и доменов
    is_spam, spam_reason = check_submission_for_spam(
        request,
        name=name,
        email=email,
        phone=phone,
        subject=subject,
        body=body,
        website=website,
    )
    if is_spam:
        logger.warning(
            "Форма обратной связи: спам отклонён (%s) — email=%s name=%s",
            spam_reason,
            email,
            name,
        )
        # Нейтральный ответ успеха боту, без сохранения в БД и без уведомлений
        _add_flash(request, "Спасибо! Сообщение отправлено. Мы свяжемся с вами.", "success")
        return RedirectResponse(url=str(request.url_for("contact")), status_code=303)

    values = {"name": name, "email": email, "phone": phone, "subject": subject, "body": body}
    if not _captcha_ok(request, captcha):
        return _contact_page(
            request,
            status_code=422,
            field_errors={"captcha": ["Неверный код с картинки. Попробуйте ещё раз."]},
            form_values=values,
        )
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
        for err in e.errors():
            loc = err.get("loc", ())
            if loc:
                field = str(loc[0])
                msg = str(err.get("msg") or "Проверьте это поле")
                if msg.lower().startswith("value error, "):
                    msg = msg[13:]
                errs.setdefault(field, []).append(msg)
        return _contact_page(
            request,
            status_code=422,
            field_errors=errs,
            form_values=values,
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


@app.get("/contact/captcha.png", include_in_schema=False)
def contact_captcha_png(request: Request):
    refresh = request.query_params.get("refresh")
    data = request.session.get("contact_captcha")
    expired = not data or time.time() > float((data or {}).get("exp") or 0)
    if refresh or expired or not (data or {}).get("code"):
        _captcha_issue(request)
        data = request.session.get("contact_captcha") or {}
    code = str((data or {}).get("code") or "")
    if not code:
        code = _captcha_issue(request)
    png = render_png(code)
    return Response(
        content=png,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
        },
    )


@app.get("/robots.txt", response_class=Response)
def robots_txt(request: Request):
    site = Config.SITE_URL.rstrip("/")
    body = f"""User-agent: *
Allow: /
Disallow: /admin
Disallow: /admin/
Disallow: /api/
Disallow: /contact/captcha.png

Host: sergeymarkin.ru
Sitemap: {site}/sitemap.xml
"""
    return Response(content=body, media_type="text/plain; charset=utf-8")


@app.get("/sitemap.xml", response_class=Response)
def sitemap_xml(request: Request):
    site = Config.SITE_URL.rstrip("/")
    today = datetime.now().strftime("%Y-%m-%d")
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
        lines.append(f"    <lastmod>{today}</lastmod>")
        lines.append(f"    <changefreq>{changefreq}</changefreq>")
        lines.append(f"    <priority>{priority}</priority>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return Response(content="\n".join(lines), media_type="application/xml; charset=utf-8")


@app.get("/yandex_ba5eac75b0bf5a4c.html", response_class=FileResponse, include_in_schema=False)
def yandex_verification():
    return FileResponse(BASE_DIR / "public" / "yandex_ba5eac75b0bf5a4c.html")


@app.get("/googled538d210272879fb.html", response_class=FileResponse, include_in_schema=False)
def google_verification():
    return FileResponse(BASE_DIR / "public" / "googled538d210272879fb.html")


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


app.mount("/", StaticFiles(directory=str(BASE_DIR / "public")), name="public")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
