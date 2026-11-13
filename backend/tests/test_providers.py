"""Provider switching uses the selected brain, including a mocked one."""

from __future__ import annotations

from alex.llm.base import StreamEvent
from alex.llm.providers import get_router


class ScriptedProvider:
    id = "mock"
    label = "Mock provider"

    def __init__(self) -> None:
        self.rounds = 0

    def is_configured(self) -> bool:
        return True

    def status_detail(self) -> str:
        return "Scripted test provider."

    async def stream(self, messages, tools, model):
        del messages, tools
        self.rounds += 1
        yield StreamEvent.text("mock-")
        yield StreamEvent.text(model or "nomodel")

    async def probe(self, model):
        return {"ok": True, "detail": f"mock {model}"}


class ToolLoopProvider:
    id = "toolmock"
    label = "Tool mock"

    def __init__(self) -> None:
        self.rounds = 0

    def is_configured(self) -> bool:
        return True

    def status_detail(self) -> str:
        return "Emits one tool call, then a summary."

    async def stream(self, messages, tools, model):
        del messages, tools, model
        self.rounds += 1
        if self.rounds == 1:
            yield StreamEvent.tool(
                "c1",
                "text_utility",
                {"operation": "word_count", "text": "one two three"},
            )
            return
        yield StreamEvent.text("three words")

    async def probe(self, model):
        return {"ok": True, "detail": "ok"}


def _chat(client, content: str):
    texts = []
    tools = []
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "chat", "content": content})
        while True:
            message = ws.receive_json()
            if message["type"] == "token":
                texts.append(message["text"])
            elif message["type"] == "tool_result":
                tools.append(message)
            elif message["type"] == "error":
                raise AssertionError(message["detail"])
            elif message["type"] == "done":
                break
    return "".join(texts), tools


def test_switch_to_mocked_provider(client):
    get_router().register(ScriptedProvider())
    response = client.put("/api/settings", json={"provider": "mock", "model": "unit-model"})
    assert response.status_code == 200
    assert response.json()["provider"] == "mock"
    text, _tools = _chat(client, "Hello Sahib")
    assert text == "mock-unit-model"
    switched = client.put("/api/settings", json={"provider": "offline", "model": ""})
    assert switched.status_code == 200
    assert client.get("/api/settings").json()["provider"] == "offline"


def test_mocked_provider_tool_loop(client):
    get_router().register(ToolLoopProvider())
    assert client.put("/api/settings", json={"provider": "toolmock", "model": "x"}).status_code == 200
    text, tools = _chat(client, "Count these words")
    assert tools[0]["name"] == "text_utility"
    assert tools[0]["output"] == "3"
    assert text == "three words"


def test_unconfigured_openai_is_explicit(client):
    assert client.put("/api/settings", json={"provider": "openai", "model": "gpt-4o-mini"}).status_code == 200
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "chat", "content": "Hello"})
        while True:
            message = ws.receive_json()
            if message["type"] == "error":
                assert "platform.openai.com" in message["detail"]
                break
            if message["type"] == "done":
                raise AssertionError("OpenAI answered without a key")
    status = client.get("/api/system/status").json()
    assert status["provider"] == "openai"
    assert status["provider_configured"] is False
