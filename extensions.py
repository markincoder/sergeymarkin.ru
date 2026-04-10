# -*- coding: utf-8 -*-
"""Расширения Flask (избегаем циклических импортов)."""
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "admin_login"
login_manager.login_message_category = "info"
