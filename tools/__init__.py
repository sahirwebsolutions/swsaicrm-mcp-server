"""Auto-discover concrete `BaseTool` implementations (no manual registration lists)."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path
from typing import Type

import mcp.types as mcp_types

from tools.base import BaseTool


def _iter_tool_classes() -> list[Type[BaseTool]]:
    pkg_dir = Path(__file__).resolve().parent
    classes: list[Type[BaseTool]] = []
    for mod in pkgutil.iter_modules([str(pkg_dir)]):
        if mod.ispkg:
            continue
        if mod.name.startswith("_") or mod.name in ("base",):
            continue
        imported = importlib.import_module(f"{__name__}.{mod.name}")
        for _n, obj in inspect.getmembers(imported, inspect.isclass):
            if obj is BaseTool or not issubclass(obj, BaseTool):
                continue
            if inspect.isabstract(obj):
                continue
            classes.append(obj)
    return sorted(classes, key=lambda c: c.name)


def load_tool_classes() -> list[Type[BaseTool]]:
    return _iter_tool_classes()


def mcp_tool_definitions(classes: list[Type[BaseTool]]) -> list[mcp_types.Tool]:
    out: list[mcp_types.Tool] = []
    for cls in classes:
        out.append(
            mcp_types.Tool(
                name=cls.name,
                title=cls.name,
                description=cls.description,
                inputSchema=cls.input_schema(),
            )
        )
    return out


def tool_registry(classes: list[Type[BaseTool]]) -> dict[str, Type[BaseTool]]:
    return {c.name: c for c in classes}
