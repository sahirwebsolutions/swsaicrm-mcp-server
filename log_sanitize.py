"""Redact PII and bound log payload size."""

from __future__ import annotations

import json
import re
from typing import Any

_EMAIL_LIKE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
_PHONE_LIKE = re.compile(r"\+?\d[\d\s().-]{7,}\d")

_SENSITIVE_KEYS = frozenset(
    {
        "email",
        "email_2",
        "phone",
        "phone_2",
        "phone_3",
        "phone_4",
        "notes",
        "description",
        "title",  # free text in task titles can be PII — redact content not key
        "background",
        "text",
        "body",
        "message",
        "query",
        "search",
    }
)

_MAX_LOG_LEN = 2000


def redact_value(key: str | None, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            sk = str(k)
            if sk.lower() in _SENSITIVE_KEYS:
                out[sk] = "[redacted]"
            elif isinstance(v, (dict, list)):
                out[sk] = redact_value(sk, v)
            elif isinstance(v, str):
                out[sk] = _redact_string(v)
            else:
                out[sk] = v
        return out
    if isinstance(value, list):
        return [redact_value(key, x) for x in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value


def _redact_string(s: str) -> str:
    s2 = _EMAIL_LIKE.sub("[email]", s)
    s2 = _PHONE_LIKE.sub("[phone]", s2)
    return s2


def safe_log_json(event: dict[str, Any]) -> str:
    red = redact_value(None, event)
    raw = json.dumps(red, default=str, ensure_ascii=False)
    if len(raw) > _MAX_LOG_LEN:
        return raw[: _MAX_LOG_LEN - 3] + "..."
    return raw
