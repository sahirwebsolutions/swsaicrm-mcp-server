"""Scope guard and audit fingerprint helpers."""

from __future__ import annotations

from scope_guard import forbidden_identity_argument, is_identity_key
from tool_logging import params_fingerprint


def test_is_identity_key_case_and_dash():
    assert is_identity_key("workspace_id")
    assert is_identity_key("Workspace_Id")
    assert is_identity_key("x-workspace-id")
    assert not is_identity_key("contact_id")


def test_forbidden_identity_in_norm_args():
    assert forbidden_identity_argument({"foo": 1}) is None
    assert forbidden_identity_argument({"profile_id": "x"}) == "profile_id"
    assert forbidden_identity_argument({"Current-Workspace-Id": "w"}) == "Current-Workspace-Id"


def test_params_fingerprint_stable():
    a = {"b": 1, "a": 2}
    b = {"a": 2, "b": 1}
    assert params_fingerprint(a) == params_fingerprint(b)
    assert len(params_fingerprint(a)) == 16
