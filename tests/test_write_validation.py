"""Write-tool schema validation (reject unknown fields, enums via pydantic)."""

from __future__ import annotations

import pytest

from tools.base import validate_args
from tools.deals import CreateDealParams


def test_deals_rejects_unknown_fields():
    with pytest.raises(ValueError):
        validate_args({"name": "X", "extra_field": True}, CreateDealParams)


def test_tools_discovery_includes_deals():
    from tools import load_tool_classes

    names = {c.name for c in load_tool_classes()}
    assert "list_deals" in names
    assert "create_deal" in names
    assert "list_pipelines" in names
