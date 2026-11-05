"""Smart natural-language date-range parsing for read tools.

Turns conversational ranges ("last 7 days", "this month", "yesterday") into concrete
``(start, end)`` ISO dates so the AI doesn't have to compute calendar math. Explicit
ISO dates pass through unchanged. All computation is UTC-date based (YYYY-MM-DD).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Tuple


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _iso(d: date) -> str:
    return d.isoformat()


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _month_end(d: date) -> date:
    if d.month == 12:
        return d.replace(day=31)
    return (d.replace(month=d.month + 1, day=1) - timedelta(days=1))


def parse_relative_range(
    expr: Optional[str],
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Resolve a date range.

    Precedence: explicit ``start``/``end`` win; otherwise ``expr`` (natural language)
    is parsed. Returns ``(start_iso, end_iso)`` — either may be ``None`` (open-ended).
    """
    # Explicit ISO dates take precedence.
    s = _clean_iso(start)
    e = _clean_iso(end)
    if s or e:
        return s, e

    if not expr:
        return None, None

    t = str(expr).strip().lower()
    today = _today()

    if t in ("today",):
        return _iso(today), _iso(today)
    if t in ("yesterday",):
        y = today - timedelta(days=1)
        return _iso(y), _iso(y)
    if t in ("this week",):
        monday = today - timedelta(days=today.weekday())
        return _iso(monday), _iso(today)
    if t in ("last week", "past week"):
        monday = today - timedelta(days=today.weekday() + 7)
        sunday = monday + timedelta(days=6)
        return _iso(monday), _iso(sunday)
    if t in ("this month",):
        return _iso(_month_start(today)), _iso(today)
    if t in ("last month", "previous month"):
        first_this = _month_start(today)
        last_prev = first_this - timedelta(days=1)
        return _iso(_month_start(last_prev)), _iso(last_prev)
    if t in ("this year",):
        return _iso(today.replace(month=1, day=1)), _iso(today)
    if t in ("this quarter",):
        q_start_month = 3 * ((today.month - 1) // 3) + 1
        return _iso(today.replace(month=q_start_month, day=1)), _iso(today)

    # "last N days" / "past N days" (inclusive of today).
    m = re.match(r"(?:last|past)\s+(\d+)\s*(day|days|week|weeks|month|months)", t)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit.startswith("day"):
            return _iso(today - timedelta(days=n - 1)), _iso(today)
        if unit.startswith("week"):
            return _iso(today - timedelta(weeks=n)), _iso(today)
        if unit.startswith("month"):
            return _iso(today - timedelta(days=30 * n)), _iso(today)

    # "older than N days" -> only an end bound.
    m = re.match(r"older than\s+(\d+)\s*(day|days)", t)
    if m:
        n = int(m.group(1))
        return None, _iso(today - timedelta(days=n))

    # A bare ISO date in the expression.
    iso = _clean_iso(t)
    if iso:
        return iso, iso

    return None, None


def _clean_iso(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        # Accept YYYY-MM-DD or full ISO datetime; normalize to date.
        if "t" in s.lower():
            return datetime.fromisoformat(s.replace("Z", "+00:00")).date().isoformat()
        return date.fromisoformat(s).isoformat()
    except (TypeError, ValueError):
        return None
