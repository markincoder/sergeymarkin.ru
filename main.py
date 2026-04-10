# -*- coding: utf-8 -*-
"""Альтернативная точка входа: python main.py"""
from app import app

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
