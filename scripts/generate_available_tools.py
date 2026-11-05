#!/usr/bin/env python3
"""Generate `docs/reference/AVAILABLE_TOOLS.md` from the LIVE tool registry.

Why generate instead of hand-writing: the tool catalog then never drifts from the
code. Every tool's name, "when to call" description, and input schema come straight
from the registered `BaseTool` classes, so `list_tools` (what the AI actually sees)
and the docs are guaranteed to match.

Usage:
    ./.venv/bin/python scripts/generate_available_tools.py            # write file
    ./.venv/bin/python scripts/generate_available_tools.py --check    # CI: fail if stale
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

# Make the mcp-server package importable when run from anywhere.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools import load_tool_classes  # noqa: E402

try:
    from unified_transport import routes_via_unified_executor  # noqa: E402
except Exception:  # pragma: no cover - transport optional at doc-gen time
    def routes_via_unified_executor(_name: str) -> bool:  # type: ignore
        return False

OUTPUT = _ROOT / "docs" / "reference" / "AVAILABLE_TOOLS.md"

# Friendly domain grouping keyed by the tool's module basename.
_DOMAINS = {
    "identity": "Identity & Session",
    "contacts": "Contacts & Leads",
    "deals": "Deals & Pipelines",
    "tasks": "Tasks",
    "boards": "Task Boards",
}
_DOMAIN_ORDER = ["identity", "contacts", "deals", "tasks", "boards"]

_WRITE_PREFIXES = ("create_", "update_", "delete_", "add_", "move_", "assign_", "set_")
_DESTRUCTIVE_PREFIXES = ("delete_", "remove_")


def _module_key(cls: Any) -> str:
    mod = getattr(cls, "__module__", "") or ""
    return mod.rsplit(".", 1)[-1]


def _kind(name: str) -> str:
    if name.startswith(_DESTRUCTIVE_PREFIXES):
        return "destructive"
    if name.startswith(_WRITE_PREFIXES):
        return "write"
    return "read"


def _kind_badge(kind: str) -> str:
    return {
        "read": "🟢 read-only",
        "write": "🟠 write",
        "destructive": "🔴 destructive",
    }.get(kind, kind)


def _type_str(spec: dict[str, Any]) -> str:
    if not isinstance(spec, dict):
        return "any"
    if "type" in spec:
        t = spec["type"]
        if t == "array":
            item = spec.get("items", {})
            return f"array<{_type_str(item)}>"
        return str(t)
    # Optionals render as anyOf[type, null] in pydantic JSON schema.
    for key in ("anyOf", "oneOf", "allOf"):
        if key in spec and isinstance(spec[key], list):
            parts = [
                _type_str(s)
                for s in spec[key]
                if not (isinstance(s, dict) and s.get("type") == "null")
            ]
            return " | ".join(dict.fromkeys(parts)) or "any"
    if "$ref" in spec:
        return spec["$ref"].rsplit("/", 1)[-1]
    if spec.get("format"):
        return str(spec["format"])
    return "any"


def _params_table(schema: dict[str, Any]) -> str:
    props = (schema or {}).get("properties") or {}
    required = set((schema or {}).get("required") or [])
    if not props:
        return "_No parameters._\n"
    lines = ["| Parameter | Type | Required | Notes |", "| --- | --- | --- | --- |"]
    for pname, pspec in props.items():
        pspec = pspec if isinstance(pspec, dict) else {}
        note = str(pspec.get("description") or "").replace("\n", " ").strip()
        if not note:
            constraints = []
            for c in ("minimum", "maximum", "minLength", "maxLength", "pattern", "default"):
                if c in pspec:
                    constraints.append(f"{c}={pspec[c]}")
            note = ", ".join(constraints)
        req = "yes" if pname in required else "no"
        lines.append(f"| `{pname}` | {_type_str(pspec)} | {req} | {note} |")
    return "\n".join(lines) + "\n"


def build_markdown() -> str:
    classes = load_tool_classes()
    total = len(classes)
    reads = sum(1 for c in classes if _kind(c.name) == "read")
    writes = sum(1 for c in classes if _kind(c.name) in ("write", "destructive"))

    grouped: dict[str, list[Any]] = {}
    for c in classes:
        grouped.setdefault(_module_key(c), []).append(c)

    out: list[str] = []
    out.append("# AI CRM — Available MCP Tools")
    out.append("")
    out.append(
        "> **Auto-generated** from the live tool registry by "
        "`scripts/generate_available_tools.py`. Do not edit by hand — run the "
        "generator to refresh so this catalog can never drift from the code the AI "
        "actually sees."
    )
    out.append("")
    out.append(
        f"**{total} tools** — {reads} read-only, {writes} write/destructive — across "
        f"{len(grouped)} CRM domains."
    )
    out.append("")

    # Differentiators — why this MCP is enterprise-grade.
    out.append("## Why this MCP is enterprise-grade")
    out.append("")
    out.append(
        "Unlike a typical single-tenant CRM MCP that talks straight to a REST API, "
        "every call here is **governed and multi-tenant**:"
    )
    out.append("")
    out.append(
        "- **Governed execution** — writes route through the *same* unified executor "
        "as the in-app AI, so RBAC, policy checks, audit logging, and idempotency are "
        "enforced identically whether a change comes from the app or an MCP client."
    )
    out.append(
        "- **Workspace + user scoped** — every request is authenticated and scoped to "
        "a workspace and user; tools never leak cross-tenant data."
    )
    out.append(
        "- **Resilient by default** — shared HTTP client with retries, circuit "
        "breaker, rate limiting, response caching, and backpressure."
    )
    out.append(
        "- **Idempotent writes** — create/update/delete accept an idempotency key and "
        "de-duplicate retries, so a flaky connection never double-creates records."
    )
    out.append(
        "- **Safe by design** — no arbitrary code execution. Every tool is "
        "schema-validated with an explicit input contract (a deliberate security "
        "choice for a multi-tenant server)."
    )
    out.append("")

    # Tool selection guide.
    out.append("## Tool selection guide")
    out.append("")
    out.append("| If the user wants to… | Use | Kind |")
    out.append("| --- | --- | --- |")
    out.append("| Answer a question / see / count / filter records | `list_*`, `get_*`, `*_search` | 🟢 read-only |")
    out.append("| Add a record | `create_*`, `add_*` | 🟠 write |")
    out.append("| Change a record | `update_*` | 🟠 write |")
    out.append("| Delete a record (confirm first) | `delete_*` | 🔴 destructive |")
    out.append("")
    out.append(
        "Read tools are cached and safe to call freely. Write tools are governed and "
        "idempotent — call them once you have what you need. **Destructive** tools "
        "require explicit user confirmation."
    )
    out.append("")

    # Per-domain tool detail.
    out.append("## Tools by domain")
    out.append("")
    ordered_keys = [k for k in _DOMAIN_ORDER if k in grouped] + [
        k for k in sorted(grouped) if k not in _DOMAIN_ORDER
    ]
    for key in ordered_keys:
        tools = sorted(grouped[key], key=lambda c: (_kind(c.name) != "read", c.name))
        out.append(f"### {_DOMAINS.get(key, key.title())}")
        out.append("")
        # Quick index line per domain.
        for c in tools:
            out.append(f"- [`{c.name}`](#{c.name}) — {_kind_badge(_kind(c.name))}")
        out.append("")
        for c in tools:
            kind = _kind(c.name)
            out.append(f"#### `{c.name}`")
            out.append("")
            if routes_via_unified_executor(c.name):
                gov = "  ·  governed (RBAC + audit + idempotent)" if kind != "read" else "  ·  governed (RBAC + audit)"
            else:
                gov = ""
            out.append(f"{_kind_badge(kind)}{gov}  ·  v{getattr(c, 'version', '1.0.0')}")
            out.append("")
            out.append(str(c.description or "").strip())
            out.append("")
            try:
                schema = c.input_schema()
            except Exception:
                schema = {}
            out.append(_params_table(schema))
            out.append("")

    out.append("---")
    out.append("")
    out.append(
        "_Regenerate with_ `./.venv/bin/python scripts/generate_available_tools.py`."
    )
    out.append("")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Fail if the file is stale.")
    args = parser.parse_args()

    content = build_markdown()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    if args.check:
        existing = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if existing.strip() != content.strip():
            print("AVAILABLE_TOOLS.md is stale — run scripts/generate_available_tools.py", file=sys.stderr)
            return 1
        print("AVAILABLE_TOOLS.md is up to date.")
        return 0

    OUTPUT.write_text(content, encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(_ROOT)} ({len(content)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
