"""Incremental parsers for provider streaming responses. No network."""

from __future__ import annotations

import json
from typing import Any

from alex.llm.base import StreamEvent


class OpenAIStreamParser:
    """Parses OpenAI-compatible server-sent events, including xAI."""

    def __init__(self) -> None:
        self.calls: dict[int, dict[str, str]] = {}
        self._emitted = False

    def feed_line(self, line: str) -> list[StreamEvent]:
        line = line.strip()
        if not line.startswith("data:"):
            return []
        data = line[5:].strip()
        if data == "[DONE]":
            return self._emit_tools()
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            return []
        if chunk.get("error"):
            message = chunk["error"]
            if isinstance(message, dict):
                message = message.get("message") or str(message)
            return [StreamEvent.error(str(message))]
        choice = (chunk.get("choices") or [{}])[0]
        delta = choice.get("delta") or {}
        events: list[StreamEvent] = []
        content = delta.get("content")
        if content:
            events.append(StreamEvent.text(content))
        for tc in delta.get("tool_calls") or []:
            idx = int(tc.get("index") or 0)
            slot = self.calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
            if tc.get("id"):
                slot["id"] = tc["id"]
            fn = tc.get("function") or {}
            if fn.get("name"):
                slot["name"] += fn["name"]
            if fn.get("arguments"):
                slot["arguments"] += fn["arguments"]
        if choice.get("finish_reason"):
            events.extend(self._emit_tools())
        return events

    def finish(self) -> list[StreamEvent]:
        return self._emit_tools()

    def _emit_tools(self) -> list[StreamEvent]:
        if self._emitted:
            return []
        self._emitted = True
        events: list[StreamEvent] = []
        for idx in sorted(self.calls):
            slot = self.calls[idx]
            raw = slot["arguments"]
            try:
                args: Any = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                args = {"_raw": raw}
            if not isinstance(args, dict):
                args = {"value": args}
            events.append(StreamEvent.tool(slot["id"] or f"call_{idx}", slot["name"], args))
        return events


class AnthropicStreamParser:
    def __init__(self) -> None:
        self.blocks: dict[int, dict[str, Any]] = {}

    def feed_line(self, line: str) -> list[StreamEvent]:
        line = line.strip()
        if not line.startswith("data:"):
            return []
        try:
            data = json.loads(line[5:].strip())
        except json.JSONDecodeError:
            return []
        typ = data.get("type")
        if typ == "content_block_start":
            block = data.get("content_block") or {}
            self.blocks[int(data["index"])] = {
                "type": block.get("type"),
                "id": block.get("id") or "",
                "name": block.get("name") or "",
                "json": "",
            }
            return []
        if typ == "content_block_delta":
            delta = data.get("delta") or {}
            if delta.get("type") == "text_delta" and delta.get("text"):
                return [StreamEvent.text(delta["text"])]
            if delta.get("type") == "input_json_delta":
                block = self.blocks.get(int(data["index"]))
                if block is not None:
                    block["json"] += delta.get("partial_json") or ""
            return []
        if typ == "content_block_stop":
            block = self.blocks.get(int(data.get("index", -1)))
            if not block or block.get("type") != "tool_use":
                return []
            raw = block.get("json") or "{}"
            try:
                args = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                args = {"_raw": raw}
            if not isinstance(args, dict):
                args = {"value": args}
            return [StreamEvent.tool(block.get("id") or "", block.get("name") or "", args)]
        if typ == "error":
            err = data.get("error") or data
            if isinstance(err, dict):
                err = err.get("message") or str(err)
            return [StreamEvent.error(str(err))]
        return []

    def finish(self) -> list[StreamEvent]:
        return []


class OllamaStreamParser:
    def feed_line(self, line: str) -> list[StreamEvent]:
        line = line.strip()
        if not line:
            return []
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return []
        if msg.get("error"):
            return [StreamEvent.error(str(msg["error"]))]
        events: list[StreamEvent] = []
        message = msg.get("message") or {}
        if message.get("content"):
            events.append(StreamEvent.text(message["content"]))
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function") or tc
            name = fn.get("name") or ""
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args) if args else {}
                except json.JSONDecodeError:
                    args = {"_raw": args}
            if not isinstance(args, dict):
                args = {"value": args}
            events.append(StreamEvent.tool(tc.get("id") or f"call_{name}", name, args))
        return events

    def finish(self) -> list[StreamEvent]:
        return []
