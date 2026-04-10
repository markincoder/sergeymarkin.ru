# -*- coding: utf-8 -*-
"""
Главное приложение Flask: публичные страницы, форма обратной связи, админ-панель.
"""
import logging
import sys
import threading
from pathlib import Path

# Корректный вывод кириллицы в логах в консоли Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from flask import (
    Flask,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    abort,
    current_app,
    Response,
)
from flask_login import login_user, logout_user, login_required, current_user

from config import Config
from extensions import db, login_manager
from models import User, ContactMessage
from forms import ContactForm, LoginForm, CSRFActionForm
from cases_data import CASES, get_case_by_slug
from notifications import notify_new_contact


def enqueue_contact_notifications(app: Flask, message_id: int) -> None:
    """Почта и Telegram в фоне — запрос /contact не ждёт зависший SMTP."""

    def runner() -> None:
        with app.app_context():
            m = db.session.get(ContactMessage, message_id)
            if m is not None:
                notify_new_contact(app, m)

    threading.Thread(target=runner, daemon=True).start()

# ---------------------------------------------------------------------------
# Логирование
# ---------------------------------------------------------------------------
def setup_logging(app: Flask) -> None:
    """Настройка логирования в stdout и уровня из конфига."""
    log_level = getattr(logging, app.config.get("LOG_LEVEL", "INFO"), logging.INFO)
    if not app.logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        app.logger.addHandler(handler)
        app.logger.propagate = False
    app.logger.setLevel(log_level)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)


def create_app(config_class: type = Config) -> Flask:
    """Фабрика приложения."""
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.config.from_object(config_class)

    setup_logging(app)
    app.logger.info("Приложение создаётся")

    db.init_app(app)
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id: str):
        return db.session.get(User, int(user_id))

    @app.context_processor
    def inject_seo():
        """Канонический URL, OG-картинка по умолчанию, Schema.org Person (см. SEO-инструкция.md)."""
        site = current_app.config["SITE_URL"].rstrip("/")
        path = request.path or "/"
        canonical = site + (path if path.startswith("/") else "/" + path)
        og_img = site + current_app.config.get("SEO_OG_IMAGE", "/static/images/hero-profile.svg")
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

    # --- Публичные страницы ---
    @app.route("/")
    def index():
        """Главная: hero, описание, кейсы, CTA."""
        return render_template(
            "index.html",
            cases=CASES,
            seo_title="Главная",
            meta_desc=(
                "Трансформирую хаос в алгоритмы. Промпт-инженер, вайб-кодинг, автоматизация до 50% рутины с ИИ. "
                "HR, RAG-боты, n8n, Notion."
            ),
            og_title="Сергей Маркин — Prompt Engineer | ИИ автоматизация",
        )

    @app.route("/cases")
    def cases_list():
        """Список примеров работ."""
        return render_template(
            "cases.html",
            cases=CASES,
            seo_title="Примеры работ",
            meta_desc=(
                "Примеры работ: HR-ассистент (n8n + GPT-4), умный чат-бот с RAG в Telegram, "
                "AI таск-трекер (Notion + n8n). Сергей Маркин, prompt engineer."
            ),
            og_title="Примеры работ — Сергей Маркин | AI и автоматизация",
        )

    @app.route("/cases/<slug>")
    def case_detail(slug: str):
        """Детальная страница кейса."""
        case = get_case_by_slug(slug)
        if not case:
            abort(404)
        site = app.config["SITE_URL"].rstrip("/")
        og_img_case = site + "/static/images/" + case["image"]
        case_url = site + url_for("case_detail", slug=case["slug"])
        breadcrumb_ld = {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": 1,
                    "name": "Главная",
                    "item": site + "/",
                },
                {
                    "@type": "ListItem",
                    "position": 2,
                    "name": "Примеры работ",
                    "item": site + url_for("cases_list"),
                },
                {
                    "@type": "ListItem",
                    "position": 3,
                    "name": case["title"],
                    "item": case_url,
                },
            ],
        }
        return render_template(
            "case_detail.html",
            case=case,
            seo_title=case["title"],
            meta_desc=case["short"],
            og_title=f'{case["title"]} — пример работ | Сергей Маркин',
            og_image=og_img_case,
            breadcrumb_ld=breadcrumb_ld,
        )

    @app.route("/contact", methods=["GET", "POST"])
    def contact():
        """Форма обратной связи."""
        form = ContactForm()
        if form.validate_on_submit():
            msg = ContactMessage(
                name=form.name.data.strip(),
                email=form.email.data.strip().lower(),
                phone=form.phone.data.strip(),
                subject=form.subject.data.strip(),
                body=(form.body.data or "").strip() or None,
            )
            db.session.add(msg)
            db.session.commit()
            app.logger.info(
                "Новая заявка с формы: email=%s subject=%s", msg.email, msg.subject
            )
            enqueue_contact_notifications(app, msg.id)
            flash("Спасибо! Сообщение отправлено. Мы свяжемся с вами.", "success")
            return redirect(url_for("contact"))

        return render_template(
            "contact.html",
            form=form,
            seo_title="Обратная связь",
            meta_desc=(
                "Свяжитесь со мной: форма обратной связи. Обсудим проект, сроки и автоматизацию с ИИ. "
                "Сергей Маркин, prompt engineer."
            ),
            og_title="Обратная связь — Сергей Маркин",
        )

    @app.route("/robots.txt")
    def robots_txt():
        """Правила для роботов и ссылка на sitemap."""
        site = app.config["SITE_URL"].rstrip("/")
        body = f"""User-agent: *
Allow: /
Disallow: /admin

Sitemap: {site}/sitemap.xml
"""
        return Response(body, mimetype="text/plain; charset=utf-8")

    @app.route("/sitemap.xml")
    def sitemap_xml():
        """Карта сайта для Яндекса и Google (см. SEO-инструкция.md)."""
        site = app.config["SITE_URL"].rstrip("/")
        from xml.sax.saxutils import escape

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
        return Response("\n".join(lines), mimetype="application/xml; charset=utf-8")

    # --- Админ ---
    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        if current_user.is_authenticated:
            return redirect(url_for("admin_dashboard"))

        form = LoginForm()
        if form.validate_on_submit():
            user = User.query.filter_by(username=form.username.data.strip()).first()
            if user and user.check_password(form.password.data):
                login_user(user, remember=form.remember.data)
                app.logger.info("Вход в админку: %s", user.username)
                next_page = request.args.get("next")
                if next_page and next_page.startswith("/"):
                    return redirect(next_page)
                return redirect(url_for("admin_dashboard"))
            app.logger.warning("Неудачная попытка входа: %s", form.username.data)
            flash("Неверный логин или пароль.", "danger")

        return render_template(
            "admin/login.html",
            form=form,
            seo_noindex=True,
            seo_title="Вход",
            meta_desc="Служебный вход в панель управления заявками.",
            og_title="Вход в админ-панель",
        )

    @app.route("/admin/logout")
    @login_required
    def admin_logout():
        app.logger.info("Выход из админки: %s", current_user.username)
        logout_user()
        flash("Вы вышли из системы.", "info")
        return redirect(url_for("index"))

    @app.route("/admin")
    @login_required
    def admin_dashboard():
        """Таблица заявок."""
        messages = (
            ContactMessage.query.order_by(ContactMessage.created_at.desc()).all()
        )
        action_form = CSRFActionForm()
        return render_template(
            "admin/dashboard.html",
            messages=messages,
            action_form=action_form,
            seo_noindex=True,
            seo_title="Заявки",
            meta_desc="Панель заявок с формы обратной связи.",
            og_title="Заявки — админ",
        )

    @app.route("/admin/message/<int:message_id>/read", methods=["POST"])
    @login_required
    def admin_message_read(message_id: int):
        form = CSRFActionForm()
        if not form.validate_on_submit():
            flash("Ошибка CSRF. Повторите действие.", "danger")
            return redirect(url_for("admin_dashboard"))

        msg = db.session.get(ContactMessage, message_id)
        if msg:
            msg.is_read = True
            db.session.commit()
            app.logger.info("Заявка %s отмечена прочитанной", message_id)
            flash("Заявка отмечена как прочитанная.", "success")
        else:
            flash("Заявка не найдена.", "warning")
        return redirect(url_for("admin_dashboard"))

    @app.route("/admin/message/<int:message_id>/unread", methods=["POST"])
    @login_required
    def admin_message_unread(message_id: int):
        form = CSRFActionForm()
        if not form.validate_on_submit():
            flash("Ошибка CSRF.", "danger")
            return redirect(url_for("admin_dashboard"))

        msg = db.session.get(ContactMessage, message_id)
        if msg:
            msg.is_read = False
            db.session.commit()
            app.logger.info("Заявка %s отмечена непрочитанной", message_id)
        return redirect(url_for("admin_dashboard"))

    @app.route("/admin/message/<int:message_id>/delete", methods=["POST"])
    @login_required
    def admin_message_delete(message_id: int):
        form = CSRFActionForm()
        if not form.validate_on_submit():
            flash("Ошибка CSRF.", "danger")
            return redirect(url_for("admin_dashboard"))

        msg = db.session.get(ContactMessage, message_id)
        if msg:
            db.session.delete(msg)
            db.session.commit()
            app.logger.info("Заявка %s удалена", message_id)
            flash("Заявка удалена.", "info")
        return redirect(url_for("admin_dashboard"))

    # --- Инициализация БД ---
    with app.app_context():
        _ensure_database_dir()
        db.create_all()
        _seed_admin_if_needed(app)

    @app.errorhandler(404)
    def not_found(_e):
        return (
            render_template(
                "errors/404.html",
                seo_title="Страница не найдена",
                meta_desc="Страница не найдена. Сергей Маркин — prompt engineer, AI и автоматизация.",
                og_title="404 — страница не найдена",
                seo_noindex=True,
            ),
            404,
        )

    return app


def _ensure_database_dir() -> None:
    """Создать папку database/ для SQLite."""
    db_path = Path(__file__).resolve().parent / "database"
    db_path.mkdir(parents=True, exist_ok=True)


def _seed_admin_if_needed(app: Flask) -> None:
    """Создать администратора по данным из конфига, если таблица пуста."""
    if User.query.first():
        return
    u = User(username=app.config["ADMIN_USERNAME"])
    u.set_password(app.config["ADMIN_PASSWORD"])
    db.session.add(u)
    db.session.commit()
    app.logger.warning(
        "Создан администратор по умолчанию: логин=%s (смените пароль в продакшене!)",
        u.username,
    )


# Точка входа: python app.py
app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
