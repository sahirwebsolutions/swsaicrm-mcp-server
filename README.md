# CRM MCP server

Thin, stateless MCP adapter in front of the FastAPI CRM (`/api/v1/*`). It validates JWTs, enforces limits, traces requests, and forwards calls—**no business logic** and **no database**.

## Requirements

- Python **3.11+**
- A CRM access JWT that includes `profile_id` and **`workspace_id`** (or `current_workspace_id`) claims, plus `type=access`.  
  *If your CRM tokens only carry `profile_id` today, add `workspace_id` to the issued access token or mint MCP-specific JWTs that include it.*

## Install

```bash
cd mcp-server
python3.11 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # edit values
```

## Run locally (stdio / Cursor)

Used for local IDE integration. Provide the same bearer token the SPA would send (or a dedicated token with `workspace_id` in claims).

```bash
export CRM_API_BASE_URL=http://localhost:8000
export JWT_SECRET=your_jwt_secret   # Same as CRM JWT_SECRET_KEY if using HS256
export MCP_TRANSPORT=stdio
export MCP_BEARER_TOKEN=eyJ...      # CRM access JWT
python main.py
```

### Cursor MCP config

Use the **absolute path** to `main.py` in your project:

```json
{
  "mcpServers": {
    "crm": {
      "command": "/absolute/path/to/mcp-server/.venv/bin/python",
      "args": ["/absolute/path/to/mcp-server/main.py"],
      "env": {
        "CRM_API_BASE_URL": "http://localhost:8000",
        "JWT_SECRET": "your_secret_here",
        "MCP_TRANSPORT": "stdio",
        "MCP_BEARER_TOKEN": "eyJ..."
      }
    }
  }
}
```

## Run HTTP mode (SSE)

Starts a Starlette server:

- **GET** `/mcp/events` — SSE session (20s heartbeat pings)
- **POST** URL from the SSE `endpoint` event — typically `/mcp/post/?session_id=...` (MCP client handles this)

Send **`Authorization: Bearer <JWT>`** on the SSE request **and** on each POST message (the middleware reads the header per request).

```bash
export MCP_TRANSPORT=http
export MCP_PORT=3100
python main.py
```

Optional: **`Last-Event-ID`** on GET is accepted and logged for observability; resume semantics depend on the MCP client.

## Add a new tool (≤5 steps)

1. Create `tools/<name>.py` and define a concrete class extending `BaseTool` (`name`, `description`, `input_schema()`, `run()`).
2. Implement `run(self, ctx, params)` using **`ctx.auth.workspace_id`** for tenancy—**never** trust `workspace_id` from tool args (those keys are stripped at the dispatcher).
3. Use **`ctx.client._request_with_retries`** toward FastAPI paths you already expose.
4. For writes, pass an **`X-Idempotency-Key`** (handled for you on POST/PUT when the tool supplies or generates a key).
5. Restart the server—**auto-discovery** picks up the module (no manual import list).

## Testing

```bash
cd mcp-server
source .venv/bin/activate
pytest tests/ -q
```

Tests mock HTTP—**no live FastAPI** required.

## Versioning rules

- **Server**: bump `Server("crm-mcp", version="…")` in `main.py` when protocol or global behavior changes.
- **Tools**: bump each tool class’s `version` when parameters or semantics change; clients read `_meta.tool_version` in responses.
- Keep changes backward compatible when possible; document breaking tool schema updates in release notes.

## Security notes

- Do not log JWTs, raw emails, or phone numbers in JSON logs (application logs only structured metadata).
- `X-User-Id` / `X-Workspace-Id` are forwarded for tracing; **authorization remains the Bearer token** matching FastAPI’s own verifier.
- **True write idempotency** requires upstream FastAPI to honor **`X-Idempotency-Key`**; the MCP layer always forwards it for writes as specified.

## Hardening (retries, scale, storms)

- **Idempotency (writes):** `X-Idempotency-Key` is `sha256(workspace_id:tool_name:tool_version:canonical_json(params))` using sorted keys and stable JSON (`canonical_json`).
- **Cache:** TTL cache keys are `{workspace_id}:{tool_name}:{hash}`; successful **create_task** / **update_task_status** invalidate `list_tasks` and `search_contacts` entries for that workspace.
- **Rate limits:** Set **`REDIS_URL`** to use Redis per-minute counters (`rate:user:…`, `rate:workspace:…`, `rate:global:…`). If Redis is unset or unreachable, the server falls back to the existing in-memory limiter.
- **Coalescing:** Identical concurrent tool calls (same workspace, tool, normalized arguments) share one in-flight execution.
- **Circuit breaker:** Configurable via `CIRCUIT_*` env vars; repeated upstream 5xx opens the circuit and returns `error=upstream_unavailable` until cooldown.
- **SSE:** Outbound events are bounded (queue 100); on overflow the oldest pending chunk is dropped and an `sse_backpressure` log line is emitted.

## Horizontal scaling

Without Redis, **rate limits and cache remain per-process**. Set **`REDIS_URL`** for consistent rate limits across replicas; caching is still in-memory unless you add a shared cache later.
