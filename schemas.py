# -*- coding: utf-8 -*-
"""Pydantic-схемы для форм."""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, field_validator
from pydantic_core import PydanticCustomError


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^[\d\s\+\-\(\)]+$")


def _as_stripped(v: Any) -> str:
    if isinstance(v, str):
        return v.strip()
    return ""


class ContactFormSchema(BaseModel):
    name: str
    email: str
    phone: str
    subject: str
    body: str | None = None

    @field_validator("name", mode="before")
    @classmethod
    def name_ok(cls, v: Any) -> str:
        s = _as_stripped(v)
        if len(s) < 2:
            raise PydanticCustomError("name_required", "Укажите имя")
        if len(s) > 120:
            raise PydanticCustomError("name_too_long", "Имя слишком длинное")
        return s

    @field_validator("email", mode="before")
    @classmethod
    def email_ok(cls, v: Any) -> str:
        s = _as_stripped(v).lower()
        if not s:
            raise PydanticCustomError("email_required", "Укажите email")
        if not _EMAIL_RE.match(s):
            raise PydanticCustomError(
                "email_invalid",
                "Введите email в формате name@example.com",
            )
        return s

    @field_validator("phone", mode="before")
    @classmethod
    def phone_ok(cls, v: Any) -> str:
        s = _as_stripped(v)
        if len(s) < 5:
            raise PydanticCustomError("phone_required", "Укажите телефон")
        if len(s) > 40:
            raise PydanticCustomError("phone_too_long", "Телефон слишком длинный")
        if not _PHONE_RE.match(s):
            raise PydanticCustomError(
                "phone_invalid",
                "В телефоне допустимы только цифры, пробелы, +, - и скобки",
            )
        return s

    @field_validator("subject", mode="before")
    @classmethod
    def subject_ok(cls, v: Any) -> str:
        s = _as_stripped(v)
        if len(s) < 3:
            raise PydanticCustomError("subject_required", "Укажите тему сообщения")
        if len(s) > 200:
            raise PydanticCustomError("subject_too_long", "Тема слишком длинная")
        return s

    @field_validator("body", mode="before")
    @classmethod
    def body_ok(cls, v: Any) -> str | None:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        s = v.strip() if isinstance(v, str) else ""
        if len(s) > 5000:
            raise PydanticCustomError("body_too_long", "Сообщение слишком длинное — сократите текст")
        return s or None


class LoginFormSchema(BaseModel):
    username: str
    password: str
    remember: bool = False

    @field_validator("username", mode="before")
    @classmethod
    def strip_user(cls, v: Any) -> str:
        s = _as_stripped(v)
        if not s:
            raise PydanticCustomError("username_required", "Введите логин")
        if len(s) > 80:
            raise PydanticCustomError("username_too_long", "Логин слишком длинный")
        return s

    @field_validator("password", mode="before")
    @classmethod
    def password_ok(cls, v: Any) -> str:
        s = v if isinstance(v, str) else ""
        if not s:
            raise PydanticCustomError("password_required", "Введите пароль")
        return s
