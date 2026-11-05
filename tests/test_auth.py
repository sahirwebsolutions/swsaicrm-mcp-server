import os
from unittest.mock import patch

import pytest
from jose import jwt

from auth import AuthError, decode_bearer_jwt


def test_decode_valid_jwt():
    secret = "test-secret"
    payload = {
        "profile_id": "user-1",
        "workspace_id": "ws-1",
        "type": "access",
        "exp": 9_999_999_999,
    }
    tok = jwt.encode(payload, secret, algorithm="HS256")
    ctx = decode_bearer_jwt(tok, secret=secret, algorithms=["HS256"])
    assert ctx.user_id == "user-1"
    assert ctx.workspace_id == "ws-1"


def test_missing_workspace():
    secret = "test-secret"
    payload = {
        "profile_id": "user-1",
        "type": "access",
        "exp": 9_999_999_999,
    }
    tok = jwt.encode(payload, secret, algorithm="HS256")
    with pytest.raises(AuthError) as e:
        decode_bearer_jwt(tok, secret=secret, algorithms=["HS256"])
    assert e.value.code == "auth_failed"


def test_invalid_signature():
    payload = {
        "profile_id": "user-1",
        "workspace_id": "ws-1",
        "type": "access",
        "exp": 9_999_999_999,
    }
    tok = jwt.encode(payload, "a", algorithm="HS256")
    with pytest.raises(AuthError):
        decode_bearer_jwt(tok, secret="b", algorithms=["HS256"])
