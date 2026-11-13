"""Plugin-friendly tool registry."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    ok: bool
    output: str
    sources: list[dict[str, str]] = field(default_factory=list)


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    needs_approval: bool
    handler: Callable[..., Awaitable[ToolResult]]


@dataclass
class ActionRequest:
    tool: str
    summary: str
    arguments: dict[str, Any]
    risk: str


class Registry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def tool(
        self,
        *,
        name: str,
        description: str,
        parameters: dict[str, Any],
        needs_approval: bool,
        handler: Callable[..., Awaitable[ToolResult]],
    ) -> None:
        self._tools[name] = ToolSpec(name, description, parameters, needs_approval, handler)

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def all(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def schemas(self) -> list[dict[str, Any]]:
        schemas = []
        for spec in self._tools.values():
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": spec.name,
                        "description": spec.description,
                        "parameters": spec.parameters,
                    },
                }
            )
        return schemas

    def public_list(self) -> list[dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "needs_approval": spec.needs_approval,
            }
            for spec in self._tools.values()
        ]
