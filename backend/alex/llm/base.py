"""Shared stream events and the provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StreamEvent:
    kind: str
    text: str = ""
    call_id: str = ""
    name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def text(text: str) -> StreamEvent:
        return StreamEvent("text", text=text)

    @staticmethod
    def tool(call_id: str, name: str, arguments: dict[str, Any] | None) -> StreamEvent:
        return StreamEvent("tool_call", call_id=call_id, name=name, arguments=arguments or {})

    @staticmethod
    def error(text: str) -> StreamEvent:
        return StreamEvent("error", text=text)


class LLMProvider(ABC):
    id: str
    label: str

    @abstractmethod
    def is_configured(self) -> bool: ...

    @abstractmethod
    def status_detail(self) -> str: ...

    @abstractmethod
    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str,
    ) -> AsyncIterator[StreamEvent]: ...

    async def probe(self, model: str) -> dict[str, Any]:
        if not self.is_configured():
            return {"ok": False, "detail": self.status_detail()}
        return {"ok": True, "detail": self.status_detail()}
