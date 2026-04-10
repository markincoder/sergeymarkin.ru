# -*- coding: utf-8 -*-
"""Формы WTForms с валидацией."""
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, TextAreaField, SubmitField, BooleanField
from wtforms.validators import DataRequired, Email, Length, Optional, Regexp


def _strip(s):
    return s.strip() if isinstance(s, str) else s


class ContactForm(FlaskForm):
    """Форма обратной связи."""

    name = StringField(
        "Имя",
        filters=[_strip],
        validators=[
            DataRequired(message="Укажите имя"),
            Length(min=2, max=120, message="От 2 до 120 символов"),
        ],
    )
    email = StringField(
        "Email",
        filters=[_strip],
        validators=[
            DataRequired(message="Укажите email"),
            Email(message="Некорректный email"),
            Length(max=120),
        ],
    )
    phone = StringField(
        "Телефон",
        filters=[_strip],
        validators=[
            DataRequired(message="Укажите телефон"),
            Length(min=5, max=40, message="От 5 до 40 символов"),
            Regexp(
                r"^[\d\s\+\-\(\)]+$",
                message="Допустимы цифры, пробелы, +, -, скобки",
            ),
        ],
    )
    subject = StringField(
        "Тема сообщения",
        filters=[_strip],
        validators=[
            DataRequired(message="Укажите тему"),
            Length(min=3, max=200, message="От 3 до 200 символов"),
        ],
    )
    body = TextAreaField(
        "Сообщение (необязательно)",
        validators=[Optional(), Length(max=5000)],
    )
    submit = SubmitField("Отправить")


class LoginForm(FlaskForm):
    """Вход в админ-панель."""

    username = StringField("Логин", validators=[DataRequired(), Length(max=80)])
    password = PasswordField("Пароль", validators=[DataRequired()])
    remember = BooleanField("Запомнить меня")
    submit = SubmitField("Войти")


class CSRFActionForm(FlaskForm):
    """Только CSRF для POST-действий в админке (кнопки без полей)."""

    submit = SubmitField()
