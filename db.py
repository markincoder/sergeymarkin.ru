# -*- coding: utf-8 -*-
"""SQLAlchemy engine и сессии для FastAPI."""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config import Config
from models import Base

_sqlite = Config.SQLALCHEMY_DATABASE_URI.startswith("sqlite")
_kw: dict = {}
if _sqlite:
    _kw["connect_args"] = {"check_same_thread": False}

engine = create_engine(Config.SQLALCHEMY_DATABASE_URI, echo=False, **_kw)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
