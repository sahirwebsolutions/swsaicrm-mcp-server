"""Request ID propagation via contextvars."""

from __future__ import annotations

import contextvars
from uuid import uuid4

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)


def new_request_id() -> str:
    rid = str(uuid4())
    request_id_var.set(rid)
    return rid


def get_request_id() -> str | None:
    return request_id_var.get()


def set_request_id(rid: str) -> contextvars.Token:
    return request_id_var.set(rid)


def reset_request_id(token: contextvars.Token) -> None:
    request_id_var.reset(token)
