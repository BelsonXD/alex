"""Cloud and local model providers. HTTP streaming, no fabricated replies."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from alex.config import KEY_HELP, get_settings
from alex.llm.base import LLMProvider, StreamEvent
from alex.llm.offline import OfflineProvider
from alex.llm.parse import AnthropicStreamParser, OllamaStreamParser, OpenAIStreamParser


def vision_capable(provider: str, model: str) -> bool:
    name = (model or "").lower()
    if provider == "offline":
        return False
    if provider == "ollama":
        return any(token in name for token in ("llava", "vision", "bakllava", "moondream"))
    if provider == "openai":
        return any(token in name for token in ("gpt-4o", "gpt-4.1", "o4", "vision"))
    if provider == "anthropic":
        return "claude" in name
    if provider == "xai":
        return "grok" in name
    return False


class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, provider_id: str, label: str, base_url: str, key_attr: str, help_key: str) -> None:
        self.id = provider_id
        self.label = label
        self.base_url = base_url.rstrip("/")
        self.key_attr = key_attr
        self.help_key = help_key

    def _key(self) -> str:
        return str(getattr(get_settings(), self.key_attr) or "")

    def is_configured(self) -> bool:
        return bool(self._key().strip())

    def status_detail(self) -> str:
        if self.is_configured():
            return f"{self.label} key is set."
        return f"{self.label} is not configured. Add the key from {KEY_HELP[self.help_key]} to your .env file."

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str,
    ) -> AsyncIterator[StreamEvent]:
        if not self.is_configured():
            yield StreamEvent.error(self.status_detail())
            return
        payload: dict[str, Any] = {
            "model": model,
            "messages": [_openai_message(message) for message in messages],
            "stream": True,
            "temperature": 0.4,
        }
        if tools:
            payload["tools"] = tools
        headers = {"Authorization": f"Bearer {self._key()}", "Content-Type": "application/json"}
        parser = OpenAIStreamParser()
        timeout = httpx.Timeout(180, connect=20)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST", f"{self.base_url}/chat/completions", headers=headers, json=payload
                ) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf-8", errors="replace")[:800]
                        yield StreamEvent.error(f"{self.label} returned {response.status_code}: {body}")
                        return
                    async for line in response.aiter_lines():
                        for event in parser.feed_line(line):
                            yield event
                    for event in parser.finish():
                        yield event
        except httpx.HTTPError as exc:
            yield StreamEvent.error(f"Could not reach {self.label}: {exc}")

    async def probe(self, model: str) -> dict[str, Any]:
        if not self.is_configured():
            return {"ok": False, "detail": self.status_detail()}
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(
                    f"{self.base_url}/models",
                    headers={"Authorization": f"Bearer {self._key()}"},
                )
            if response.status_code >= 400:
                return {"ok": False, "detail": f"{self.label} returned {response.status_code} while listing models."}
            return {"ok": True, "detail": f"{self.label} accepted the key. Selected model: {model}."}
        except httpx.HTTPError as exc:
            return {"ok": False, "detail": f"Could not reach {self.label}: {exc}"}


class AnthropicProvider(LLMProvider):
    id = "anthropic"
    label = "Anthropic"

    def _key(self) -> str:
        return get_settings().anthropic_api_key

    def is_configured(self) -> bool:
        return bool(self._key().strip())

    def status_detail(self) -> str:
        if self.is_configured():
            return "Anthropic key is set."
        return f"Anthropic is not configured. Add a key from {KEY_HELP['anthropic']} to your .env file."

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str,
    ) -> AsyncIterator[StreamEvent]:
        if not self.is_configured():
            yield StreamEvent.error(self.status_detail())
            return
        system, converted = _anthropic_messages(messages)
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": 4096,
            "temperature": 0.4,
            "stream": True,
            "messages": converted,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [_anthropic_tool(tool) for tool in tools]
        headers = {
            "x-api-key": self._key(),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        parser = AnthropicStreamParser()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=20)) as client:
                async with client.stream(
                    "POST", "https://api.anthropic.com/v1/messages", headers=headers, json=payload
                ) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf-8", errors="replace")[:800]
                        yield StreamEvent.error(f"Anthropic returned {response.status_code}: {body}")
                        return
                    async for line in response.aiter_lines():
                        for event in parser.feed_line(line):
                            yield event
                    for event in parser.finish():
                        yield event
        except httpx.HTTPError as exc:
            yield StreamEvent.error(f"Could not reach Anthropic: {exc}")

    async def probe(self, model: str) -> dict[str, Any]:
        if not self.is_configured():
            return {"ok": False, "detail": self.status_detail()}
        payload = {
            "model": model,
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "ping"}],
        }
        headers = {
            "x-api-key": self._key(),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
            if response.status_code >= 400:
                return {"ok": False, "detail": f"Anthropic returned {response.status_code}: {response.text[:300]}"}
            return {"ok": True, "detail": f"Anthropic answered a 1-token ping with {model}."}
        except httpx.HTTPError as exc:
            return {"ok": False, "detail": f"Could not reach Anthropic: {exc}"}


class OllamaProvider(LLMProvider):
    id = "ollama"
    label = "Ollama"

    def is_configured(self) -> bool:
        return True

    def status_detail(self) -> str:
        return f"Ollama at {get_settings().ollama_base_url}. No API key. The daemon must be running."

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str,
    ) -> AsyncIterator[StreamEvent]:
        base = get_settings().ollama_base_url.rstrip("/")
        payload: dict[str, Any] = {
            "model": model,
            "messages": [_ollama_message(message) for message in messages],
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
        parser = OllamaStreamParser()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=5)) as client:
                async with client.stream("POST", f"{base}/api/chat", json=payload) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf-8", errors="replace")[:800]
                        yield StreamEvent.error(f"Ollama returned {response.status_code}: {body}")
                        return
                    async for line in response.aiter_lines():
                        for event in parser.feed_line(line):
                            yield event
                    for event in parser.finish():
                        yield event
        except httpx.HTTPError as exc:
            yield StreamEvent.error(
                f"Could not reach Ollama at {base}. Install it from {KEY_HELP['ollama']} and run `ollama pull {model}`. ({exc})"
            )

    async def probe(self, model: str) -> dict[str, Any]:
        base = get_settings().ollama_base_url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{base}/api/tags")
            if response.status_code >= 400:
                return {"ok": False, "detail": f"Ollama returned {response.status_code}."}
            names = [item.get("name") for item in response.json().get("models") or []]
            if names and not any(str(name).split(":")[0] == model.split(":")[0] for name in names):
                return {
                    "ok": True,
                    "detail": f"Ollama is running. {model} is not pulled yet. Installed: {', '.join(names)}.",
                    "models": names,
                }
            return {"ok": True, "detail": "Ollama is running.", "models": names}
        except httpx.HTTPError as exc:
            return {"ok": False, "detail": f"Ollama is not reachable at {base}. {exc}"}


class ProviderRouter:
    def __init__(self) -> None:
        self.providers: dict[str, LLMProvider] = {
            "offline": OfflineProvider(),
            "openai": OpenAICompatibleProvider(
                "openai", "OpenAI", "https://api.openai.com/v1", "openai_api_key", "openai"
            ),
            "xai": OpenAICompatibleProvider("xai", "xAI", "https://api.x.ai/v1", "xai_api_key", "xai"),
            "anthropic": AnthropicProvider(),
            "ollama": OllamaProvider(),
        }

    def get(self, name: str) -> LLMProvider:
        provider = self.providers.get(name)
        if provider is None:
            raise KeyError(name)
        return provider

    def register(self, provider: LLMProvider) -> None:
        self.providers[provider.id] = provider


_router: ProviderRouter | None = None


def get_router() -> ProviderRouter:
    global _router
    if _router is None:
        _router = ProviderRouter()
    return _router


def reset_router() -> ProviderRouter:
    global _router
    _router = ProviderRouter()
    return _router


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"
        )
    return str(content or "")


def _openai_message(message: dict[str, Any]) -> dict[str, Any]:
    role = message.get("role")
    if role == "tool":
        return {
            "role": "tool",
            "tool_call_id": message.get("tool_call_id") or "",
            "content": _text_from_content(message.get("content")),
        }
    content = message.get("content")
    converted: dict[str, Any] = {"role": role, "content": _openai_content(content)}
    if message.get("tool_calls"):
        converted["tool_calls"] = [
            {
                "id": call.get("id"),
                "type": "function",
                "function": {
                    "name": call.get("name"),
                    "arguments": json.dumps(call.get("arguments") or {}),
                },
            }
            for call in message["tool_calls"]
        ]
    return converted


def _openai_content(content: Any) -> Any:
    if isinstance(content, str) or content is None:
        return content or ""
    parts = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text":
            parts.append({"type": "text", "text": part.get("text") or ""})
        elif part.get("type") == "image":
            mime = part.get("mime") or "image/png"
            data = part.get("data") or ""
            parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}})
    return parts


def _anthropic_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role == "system":
            system_parts.append(_text_from_content(message.get("content")))
            continue
        if role == "tool":
            converted.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": message.get("tool_call_id") or "",
                            "content": _text_from_content(message.get("content")),
                        }
                    ],
                }
            )
            continue
        if role == "assistant" and message.get("tool_calls"):
            blocks: list[dict[str, Any]] = []
            text = _text_from_content(message.get("content"))
            if text:
                blocks.append({"type": "text", "text": text})
            for call in message["tool_calls"]:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call.get("id"),
                        "name": call.get("name"),
                        "input": call.get("arguments") or {},
                    }
                )
            converted.append({"role": "assistant", "content": blocks})
            continue
        converted.append({"role": role, "content": _anthropic_content(message.get("content"))})
    return "\n\n".join(part for part in system_parts if part), converted


def _anthropic_content(content: Any) -> Any:
    if isinstance(content, str) or content is None:
        return content or ""
    blocks = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text":
            blocks.append({"type": "text", "text": part.get("text") or ""})
        elif part.get("type") == "image":
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": part.get("mime") or "image/png",
                        "data": part.get("data") or "",
                    },
                }
            )
    return blocks


def _anthropic_tool(tool: dict[str, Any]) -> dict[str, Any]:
    function = tool.get("function") or tool
    return {
        "name": function.get("name"),
        "description": function.get("description") or "",
        "input_schema": function.get("parameters") or {"type": "object", "properties": {}},
    }


def _ollama_message(message: dict[str, Any]) -> dict[str, Any]:
    role = message.get("role")
    if role == "tool":
        return {"role": "tool", "content": _text_from_content(message.get("content"))}
    text = _text_from_content(message.get("content"))
    images = []
    content = message.get("content")
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "image":
                images.append(part.get("data") or "")
    converted: dict[str, Any] = {"role": "assistant" if role == "assistant" else role, "content": text}
    if images:
        converted["images"] = images
    if message.get("tool_calls"):
        converted["tool_calls"] = [
            {"function": {"name": call.get("name"), "arguments": call.get("arguments") or {}}}
            for call in message["tool_calls"]
        ]
    return converted
