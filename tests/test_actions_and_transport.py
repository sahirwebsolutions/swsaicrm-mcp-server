"""Action tools, task filters, result shaping, and the Streamable HTTP app."""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import timedelta
from typing import Any

import httpx
import pytest
from jose import jwt

from auth import AuthContext
from cache import TtlCache
from coalescing import RequestCoalescer
from config import load_settings
from context_state import cache_principal_var
from middleware import ToolContext
from response_shape import fit
from tools import load_tool_classes, mcp_tool_definitions
from tools.actions import CallReadActionTool, CallWriteActionTool, fill_path, split_action
from tools.tasks import ListTasksTool, due_window
from write_guard import WriteGuard

WS = "11111111-1111-4111-8111-111111111111"
ME = "33333333-3333-4333-8333-333333333333"
SECRET = "test-secret"


def test_split_and_fill_path():
    assert split_action("put  /api/v1/tasks/{task_id}") == ("PUT", "/api/v1/tasks/{task_id}")
    with pytest.raises(ValueError):
        split_action("GET https://evil.example/x")
    with pytest.raises(ValueError):
        split_action("GET /api/v1/../admin")
    assert fill_path("/api/v1/tasks/{task_id}", {"task_id": "a/b"}, WS) == "/api/v1/tasks/a%2Fb"
    assert fill_path("/api/v1/workspaces/{workspace_id}/members", {"workspace_id": "other"}, WS) == (
        f"/api/v1/workspaces/{WS}/members"
    )
    with pytest.raises(ValueError):
        fill_path("/api/v1/tasks/{task_id}", {}, WS)


def test_due_windows(monkeypatch):
    from datetime import date

    import tools.tasks as tasks

    monkeypatch.setattr(tasks, "_today", lambda: date(2026, 11, 10))
    assert due_window("overdue", None, None) == (None, "2026-11-09")
    assert due_window("next 7 days", None, None) == ("2026-11-10", "2026-11-17")
    assert due_window("this week", None, None) == ("2026-11-09", "2026-11-15")
    assert due_window(None, "2026-11-01", None) == ("2026-11-01", None)
    with pytest.raises(ValueError):
        due_window("whenever", None, None)


def test_fit_trims_largest_list_and_reports():
    body = {"tasks": [{"title": "x" * 200, "i": i} for i in range(1000)], "next_cursor": "abc"}
    out = fit(body, 10_000)
    assert len(json.dumps(out)) <= 10_000
    assert out["next_cursor"] == "abc"
    assert out["_truncated"]["received"] == 1000
    assert 0 < out["_truncated"]["returned"] < 1000
    assert fit({"a": 1}) == {"a": 1}


def test_annotations_mark_reads_and_deletes():
    defs = {t.name: t for t in mcp_tool_definitions(load_tool_classes())}
    assert defs["list_tasks"].annotations.readOnlyHint is True
    assert defs["call_read_action"].annotations.readOnlyHint is True
    assert defs["call_write_action"].annotations.readOnlyHint is False
    assert defs["call_write_action"].annotations.destructiveHint is True
    assert defs["delete_task"].annotations.destructiveHint is True
    assert defs["update_task"].annotations.destructiveHint is False


def test_schema_patterns_are_portable():
    """Clients such as ChatGPT reject the whole tool list when one pattern uses Python-only syntax."""
    import re

    found: list[tuple[str, str]] = []

    def walk(node: Any, name: str) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("pattern"), str):
                found.append((name, node["pattern"]))
            for value in node.values():
                walk(value, name)
        elif isinstance(node, list):
            for value in node:
                walk(value, name)

    for tool in mcp_tool_definitions(load_tool_classes()):
        walk(tool.inputSchema, tool.name)
    assert found
    for name, pattern in found:
        re.compile(pattern)
        assert not re.search(r"\(\?[aiLmsux]", pattern), f"{name}: inline flags are not portable: {pattern}"
        assert "(?P<" not in pattern and "\\A" not in pattern and "\\Z" not in pattern, f"{name}: {pattern}"


class _Resp:
    def __init__(self, body: Any, status: int = 200):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


class _FakeClient:
    def __init__(self, responses: dict[str, Any] | None = None):
        self.calls: list[dict[str, Any]] = []
        self.responses = responses or {}

    async def _request_with_retries(self, method, path, *, auth, params=None, json_body=None, idempotency_key=None, headers=None):
        self.calls.append({"method": method, "path": path, "params": params, "json": json_body, "idem": idempotency_key})
        return _Resp(self.responses.get(path, {"ok": True}))

    @staticmethod
    def raise_for_status(resp):
        body = resp.json()
        return body if isinstance(body, dict) else {"_data": body}


def _ctx(client: _FakeClient) -> ToolContext:
    os.environ.setdefault("CRM_API_BASE_URL", "http://crm.test")
    os.environ.setdefault("JWT_SECRET", SECRET)
    settings = load_settings()
    return ToolContext(
        settings=settings,
        auth=AuthContext(token="tok", user_id=ME, workspace_id=WS),
        client=client,  # type: ignore[arg-type]
        cache=TtlCache(10),
        rate_limiter=None,
        request_id="r1",
        coalescer=RequestCoalescer(),
        write_guard=WriteGuard(8),
    )


def test_list_tasks_sends_real_filters():
    client = _FakeClient({"/api/v1/tasks/": {"tasks": [], "next_cursor": None}})
    ctx = _ctx(client)
    asyncio.run(
        ListTasksTool().run(
            ctx,
            {"assignee": ["me"], "due": "today", "priority": ["high"], "status": ["Pending"], "sort_by": "priority"},
        )
    )
    q = client.calls[0]["params"]
    assert q["assigned_to"] == [ME]
    assert q["priority"] == ["high"]
    assert q["status"] == ["pending"]
    assert q["sort_by"] == "priority"
    assert q["due_date_from"].endswith("T00:00:00Z") and q["due_date_to"].endswith("T23:59:59.999Z")
    assert q["workspace_id"] == WS


class _CatalogClient(_FakeClient):
    published = "GET /api/v1/contacts"

    async def _request_with_retries(self, method, path, *, auth, params=None, json_body=None, idempotency_key=None, headers=None):
        if path == "/api/v1/api-access/actions/describe":
            self.calls.append({"method": method, "path": path, "params": params})
            if params["action"] != self.published:
                return _Resp({"detail": "That action is not available to this connection. Search again."}, 404)
            return _Resp({"action": self.published, "injected": ["query.workspace_id"]})
        return await super()._request_with_retries(
            method, path, auth=auth, params=params, json_body=json_body, idempotency_key=idempotency_key, headers=headers
        )

    @staticmethod
    def raise_for_status(resp):
        from client import CRMClient

        return CRMClient.raise_for_status(resp)  # type: ignore[arg-type]


def test_generic_call_uses_published_path():
    client = _CatalogClient()
    asyncio.run(CallReadActionTool().run(_ctx(client), {"action": "GET /api/v1/contacts/"}))
    assert client.calls[-1]["path"] == "/api/v1/contacts"
    client = _CatalogClient()
    with pytest.raises(Exception) as err:
        asyncio.run(CallReadActionTool().run(_ctx(client), {"action": "GET /api/v1/admin/users"}))
    assert "not available" in str(err.value)
    assert all(c["path"] == "/api/v1/api-access/actions/describe" for c in client.calls)


def test_validation_errors_name_the_field():
    from errors import http_status_to_code, safe_upstream_detail

    detail = [{"loc": ["query", "document_type"], "msg": "Field required", "type": "missing"}]
    assert safe_upstream_detail({"detail": detail}) == "query.document_type: Field required"
    assert http_status_to_code(422) == "invalid_params"
    assert http_status_to_code(405) == "invalid_params"


def test_overdue_hides_closed_tasks():
    rows = [{"title": "a", "status": "pending"}, {"title": "b", "status": "completed"}]
    client = _FakeClient({"/api/v1/tasks/": {"tasks": rows, "next_cursor": None}})
    out = asyncio.run(ListTasksTool().run(_ctx(client), {"due": "overdue"}))
    assert [t["title"] for t in out["data"]["tasks"]] == ["a"]
    assert out["data"]["filters_applied"]["hidden_closed"] == 1
    out = asyncio.run(ListTasksTool().run(_ctx(client), {"due": "overdue", "include_closed": True}))
    assert len(out["data"]["tasks"]) == 2


def test_write_action_pins_workspace_and_uses_idempotency():
    client = _FakeClient(
        {"/api/v1/api-access/actions/describe": {"injected": ["body.workspace_id"], "action": "POST /api/v1/tasks/"}}
    )
    ctx = _ctx(client)
    asyncio.run(
        CallWriteActionTool().run(
            ctx,
            {"action": "POST /api/v1/tasks/", "body": {"title": "x", "workspace_id": "other"}, "query": {"workspace_id": "other"}},
        )
    )
    write = client.calls[-1]
    assert write["method"] == "POST"
    assert write["json"]["workspace_id"] == WS
    assert write["params"]["workspace_id"] == WS
    assert write["idem"]

    with pytest.raises(ValueError):
        asyncio.run(CallReadActionTool().run(ctx, {"action": "DELETE /api/v1/tasks/{task_id}", "path_params": {"task_id": "1"}}))


def test_cache_is_scoped_to_member():
    cache = TtlCache(10)
    cache_principal_var.set("a")
    key_a = cache.key_for(WS, "list_tasks", {"x": 1})
    cache_principal_var.set("b")
    key_b = cache.key_for(WS, "list_tasks", {"x": 1})
    assert key_a != key_b
    assert key_a.startswith(f"{WS}:list_tasks:")


def _token(**extra: Any) -> str:
    claims = {"type": "access", "profile_id": ME, "workspace_id": WS, "exp": int(time.time()) + 600, **extra}
    return jwt.encode(claims, SECRET, algorithm="HS256")


@pytest.fixture()
def http_app(monkeypatch):
    monkeypatch.setenv("CRM_API_BASE_URL", "https://api.example.test")
    monkeypatch.setenv("JWT_SECRET", SECRET)
    monkeypatch.setenv("APP_URL", "https://app.example.test")
    monkeypatch.setenv("MCP_PUBLIC_URL", "https://mcp.example.test")
    import access_gate
    import main

    async def allow(client, cache, auth):
        return {"whoami", "list_tasks", "search_actions"}, None

    monkeypatch.setattr(main, "allowed_tools", allow)
    monkeypatch.setattr(access_gate, "allowed_tools", allow)
    rt = asyncio.run(main.build_runtime_async())

    def valid(token: str) -> bool:
        try:
            main.decode_bearer_jwt(token, secret=SECRET, algorithms=["HS256"])
            return True
        except main.AuthError:
            return False

    return main.build_starlette_app(rt.server, rt.init_options, token_is_valid=valid)


def _run(app, fn):
    async def go():
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="https://mcp.example.test") as c:
                return await fn(c)

    return asyncio.run(go())


def test_discovery_and_registration(http_app):
    async def fn(c):
        pr = (await c.get("/.well-known/oauth-protected-resource")).json()
        assert pr["resource"] == "https://mcp.example.test/mcp"
        assert pr["authorization_servers"] == ["https://mcp.example.test"]
        asm = (await c.get("/.well-known/oauth-authorization-server")).json()
        assert asm["authorization_endpoint"] == "https://app.example.test/settings/api-access"
        assert asm["token_endpoint"] == "https://api.example.test/api/v1/api-access/oauth/token"
        assert asm["registration_endpoint"] == "https://mcp.example.test/register"
        reg = await c.post("/register", json={"client_name": "Claude", "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"]})
        assert reg.status_code == 201 and reg.json()["client_id"].startswith("Claude~")
        bad = await c.post("/register", json={"client_name": "x", "redirect_uris": ["http://evil.example/cb"]})
        assert bad.status_code == 400

    _run(http_app, fn)


def test_streamable_http_challenge_and_tools(http_app):
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}},
    }
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}

    async def fn(c):
        r = await c.post("/mcp", json=init, headers=headers)
        assert r.status_code == 401
        assert "resource_metadata=" in r.headers["www-authenticate"]
        r = await c.post("/mcp", json=init, headers={**headers, "Authorization": "Bearer nope"})
        assert r.status_code == 401
        auth = {**headers, "Authorization": f"Bearer {_token()}"}
        r = await c.post("/mcp", json=init, headers=auth)
        assert r.status_code == 200, r.text
        assert r.json()["result"]["serverInfo"]["name"] == "crm-mcp"
        r = await c.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=auth)
        names = {t["name"] for t in r.json()["result"]["tools"]}
        assert names == {"whoami", "list_tasks", "search_actions"}

    _run(http_app, fn)
