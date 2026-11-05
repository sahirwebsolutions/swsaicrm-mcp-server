# MCP Competitive Analysis & Upgrade Roadmap

Benchmark: **[benlaube/fub-mcp](https://github.com/benlaube/fub-mcp/)** (Follow Up Boss MCP, ~32 tools).
Goal: match its breadth and match/beat its developer experience, **without** giving up
our enterprise governance model.

## TL;DR

We are architecturally ahead where it matters for a multi-tenant SaaS (governance,
RBAC, audit, idempotency, tenancy isolation). fub-mcp is ahead on **tool breadth**,
**a `get_me` anchor**, **discovery/reporting helpers**, and **docs**. This pass closed
the docs gap and the `get_me` gap; the rest is a prioritized backlog below.

## Where we already lead

| Capability | fub-mcp | Ours |
| --- | --- | --- |
| Multi-tenant (workspace + user scoped) | Single account (API key) | ✅ Per-workspace + per-user, enforced every call |
| Governed writes (RBAC + policy + audit) | ❌ Direct REST | ✅ Routes through the same unified executor as the in-app AI |
| Idempotent writes (no double-create on retry) | Partial | ✅ Idempotency keys on all writes |
| Resilience (retry, circuit breaker, rate limit, backpressure) | Rate limit + retry | ✅ Full shared resilient client |
| Response caching | ✅ | ✅ |
| Security posture | Sandboxed Python exec | ✅ No code exec — schema-validated tools only |

## Where they lead (our gaps)

| Gap | Status | Notes |
| --- | --- | --- |
| Tool catalog doc for the AI | ✅ **Done** | `AVAILABLE_TOOLS.md`, auto-generated from the live registry (never drifts) |
| `get_me` / current-user anchor | ✅ **Done** | Added `whoami` (+ `get_me` alias) |
| "When to call" descriptions | ✅ **Done** | Every tool description rewritten to be trigger-oriented |
| Breadth of read tools (calls, events, notes, appointments, users, projects) | ✅ **Done (P0)** | `list_calls`, `list_appointments`, `list_contact_notes`, `search_notes`, `list_activities`, `list_users`, `list_projects` |
| Duplicate detection before create | ✅ **Done (P1)** | `check_duplicates(email, phone, name)` |
| Dynamic discovery (find stage/field/source by keyword) | ✅ **Done (P1)** | `find_custom_field`, `list_lead_sources`, `list_deal_stages` |
| Smart natural-language date filtering ("last 7 days") | ✅ **Done (P1)** | Shared `date_range.parse_relative_range` used by calls/appointments/reporting |
| Multi-endpoint reporting | ✅ **Done (P2)** | `generate_report` — whitelisted governed aggregations, no code exec |
| Batch operations (update N records) | ⏳ Backlog | Governed batch needs per-item policy checks |

## What shipped in this pass

1. **`AVAILABLE_TOOLS.md`** — full catalog, grouped by domain, with a tool-selection
   guide and per-tool parameter tables. **Auto-generated** via
   `scripts/generate_available_tools.py` (run `--check` in CI to prevent drift).
2. **`whoami` / `get_me`** — resolves "me"/"my" to a real user + workspace so
   first-person requests ("my tasks", "deals assigned to me", "projects I'm part of")
   are answered correctly.
3. **Trigger-oriented descriptions** on all tools — the AI now reads *when* to call a
   tool, not just what it does. Destructive tools are explicitly flagged.

## Prioritized backlog

### P0 — breadth parity (surface existing FastAPI capabilities) ✅ Shipped
Each is a thin, governed MCP tool over an endpoint we already have:
- ✅ `list_contact_notes` + `search_notes` (contact notes; workspace-wide search)
- ✅ `list_appointments` (calendar events over a date range)
- ✅ `list_calls` (call log, direction + date filters)
- ✅ `list_activities` (contact activity timeline)
- ✅ `list_users` (workspace members) — pairs naturally with `whoami`
- ✅ `list_projects` (Projects module, permission-scoped; distinct from deals)
- `list_projects` (Projects module — distinct from deals; already added on the copilot side)

### P1 — intelligence helpers ✅ Shipped
- ✅ **Duplicate detection**: `check_duplicates(email, phone, name)` before `create_contact`.
- ✅ **Smart date filtering**: shared `date_range.parse_relative_range` — read tools accept `last 7 days`, `this month`, `older than 30 days`, etc.
- ✅ **Dynamic discovery**: `find_custom_field`, `list_lead_sources`, `list_deal_stages` by keyword.

### P2 — reporting (governed, not code-exec) ✅ Shipped
fub-mcp's `execute_custom_query` runs **arbitrary Python** in a sandbox. We
**deliberately do not** copy that in a multi-tenant server — it's a security and
blast-radius risk. Instead we ship `generate_report`: a **whitelisted** set of
pre-built server-side aggregations (validated by schema, RBAC + workspace enforced by
the underlying governed endpoints), with an optional date window. Same reporting value,
no arbitrary execution.

### Cross-cutting DX
- `--check` doc-gen step in CI so the catalog can't go stale.
- Optional batch write tools once per-item policy enforcement is wired.

## Recommendation

Ship this pass now. Greenlight **P0** next (pure breadth, low risk, high value, backed
by endpoints we already have), then **P1**. Treat **P2** as a governed reporting tool,
deliberately avoiding arbitrary code execution.
