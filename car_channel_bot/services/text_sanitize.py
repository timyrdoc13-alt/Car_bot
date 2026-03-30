"""Очистка подписей перед постом в Telegram."""

from __future__ import annotations

import re

_URL_RE = re.compile(
    r"https?://[^\s\]\)]+|www\.[^\s\]\)]+",
    re.IGNORECASE,
)


def caption_without_urls(text: str) -> str:
    """Убирает http(s) и www. ссылки, сжимает пробелы."""
    if not text:
        return ""
    t = _URL_RE.sub("", text)
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = re.sub(r"  +", " ", t)
    return t.strip()
