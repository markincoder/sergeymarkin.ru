# -*- coding: utf-8 -*-
"""Pydantic-схемы для форм."""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, EmailStr, Field, field_validator


class ContactFormSchema(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: str = Field(min_length=5, max_length=40)
    subject: str = Field(min_length=3, max_length=200)
    body: str | None = Field(default=None, max_length=5000)

    @field_validator("name", "phone", "subject", mode="before")
    @classmethod
    def strip_str(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("email", mode="before")
    @classmethod
    def strip_email(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @field_validator("body", mode="before")
    @classmethod
    def strip_body(cls, v: Any) -> Any:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("phone")
    @classmethod
    def phone_chars(cls, v: str) -> str:
        if not re.match(r"^[\d\s\+\-\(\)]+$", v):
            raise ValueError("Допустимы цифры, пробелы, +, -, скобки")
        return v


class LoginFormSchema(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1)
    remember: bool = False

    @field_validator("username", mode="before")
    @classmethod
    def strip_user(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip()
        return v
