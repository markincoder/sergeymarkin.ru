# -*- coding: utf-8 -*-
"""Модели SQLAlchemy 2."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from werkzeug.security import check_password_hash, generate_password_hash


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class ContactMessage(Base):
    __tablename__ = "contact_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String(40), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<ContactMessage {self.id} {self.email}>"


class ChatBridgeSession(Base):
    """Сессия FAQ-чата: режим RAG или эскалация к оператору (Telegram)."""

    __tablename__ = "chat_bridge_sessions"

    session_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    mode: Mapped[str] = mapped_column(String(16), default="rag", nullable=False)
    telegram_anchor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Одноразовое уведомление в виджет после команды оператора «завершить чат» (отдаётся poll и сбрасывается).
    closure_pending_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Ждём ответ посетителя «да/нет» после предложения подключить оператора (слабый RAG).
    handoff_confirm_pending: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    lines: Mapped[list["ChatBridgeLine"]] = relationship(
        "ChatBridgeLine",
        back_populates="session",
        order_by="ChatBridgeLine.id",
    )


class ChatBridgeLine(Base):
    """Реплика в сессии; op_seq задаётся только для сообщений оператора из Telegram (для polling)."""

    __tablename__ = "chat_bridge_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("chat_bridge_sessions.session_id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    op_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    session: Mapped["ChatBridgeSession"] = relationship("ChatBridgeSession", back_populates="lines")


class TelegramBridgeMap(Base):
    """Исходящие message_id бота → session_id (ответ оператора через reply к цепочке)."""

    __tablename__ = "telegram_bridge_map"

    telegram_msg_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
