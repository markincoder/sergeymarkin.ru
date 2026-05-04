# -*- coding: utf-8 -*-
"""Регулярные шаблоны для эвристик чата (текст в JSON, не в коде роутов)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Final

from config import BASE_DIR

_PATH: Final = BASE_DIR / "backend" / "rag_data" / "chat_intent_patterns.json"
_FLAGS = re.I | re.UNICODE

_blob = json.loads(_PATH.read_text(encoding="utf-8"))
QUESTION_HINT_RE: Final = re.compile(_blob["question_hint"], _FLAGS)
FOLLOW_HINT_RE: Final = re.compile(_blob["follow_hint"], _FLAGS)
CASUAL_SOCIAL_RE: Final = re.compile(_blob["casual_social"], _FLAGS)
