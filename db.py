# -*- coding: utf-8 -*-
"""SQLAlchemy engine и сессии для FastAPI."""
from collections.abc import Generator

from sqlalchemy import create_engine, exc as sa_exc, text
from sqlalchemy.orm import Session, sessionmaker

from config import Config
from models import Base

_sqlite = Config.SQLALCHEMY_DATABASE_URI.startswith("sqlite")
_kw: dict = {}
if _sqlite:
    _kw["connect_args"] = {"check_same_thread": False}

engine = create_engine(Config.SQLALCHEMY_DATABASE_URI, echo=False, **_kw)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _ensure_closure_pending_column() -> None:
    """Добавить колонку на существующих БД (create_all не меняет таблицы)."""
    dialect = engine.dialect.name
    with engine.begin() as conn:
        if dialect == "sqlite":
            rows = conn.execute(text("PRAGMA table_info(chat_bridge_sessions)")).fetchall()
            names = {row[1] for row in rows}
            if "closure_pending_message" in names:
                return
            conn.execute(text("ALTER TABLE chat_bridge_sessions ADD COLUMN closure_pending_message TEXT"))
            return
        try:
            conn.execute(text("ALTER TABLE chat_bridge_sessions ADD COLUMN closure_pending_message TEXT"))
        except (sa_exc.OperationalError, sa_exc.ProgrammingError):
            pass


def _ensure_handoff_confirm_pending_column() -> None:
    with engine.begin() as conn:
        if engine.dialect.name == "sqlite":
            rows = conn.execute(text("PRAGMA table_info(chat_bridge_sessions)")).fetchall()
            names = {row[1] for row in rows}
            if "handoff_confirm_pending" in names:
                return
            conn.execute(
                text(
                    "ALTER TABLE chat_bridge_sessions ADD COLUMN handoff_confirm_pending "
                    "BOOLEAN DEFAULT 0 NOT NULL"
                )
            )
            return
        try:
            conn.execute(
                text(
                    "ALTER TABLE chat_bridge_sessions ADD COLUMN handoff_confirm_pending "
                    "BOOLEAN DEFAULT FALSE NOT NULL"
                )
            )
        except (sa_exc.OperationalError, sa_exc.ProgrammingError):
            pass


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_closure_pending_column()
    _ensure_handoff_confirm_pending_column()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
