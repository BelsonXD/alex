"""Local kernel used when no cloud model or Ollama is selected.

This is not a language model. It performs a small set of real actions — memory,
reminders, files, search, math, and approved commands — and it says so when a
question needs a full model.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from alex.llm.base import LLMProvider, StreamEvent


@dataclass
class Plan:
    text: str = ""
    tool: str | None = None
    args: dict[str, Any] | None = None


_RUN = re.compile(
    r"(?:please\s+)?(?:run|execute)\s+(?:this\s+|the\s+)?(?:powershell\s+|shell\s+|bash\s+)?(?:command\s*)?[:\-]?\s*(.+)",
    re.I | re.S,
)
_REMEMBER = re.compile(r"\bremember that\s+(.+)", re.I | re.S)
_REMIND = re.compile(
    r"\bremind me in\s+(\d+)\s*(seconds?|minutes?|hours?)\s+to\s+(.+)",
    re.I | re.S,
)
_SEARCH = re.compile(r"\b(?:search(?:\s+the\s+web)?(?:\s+for)?|look\s+up)\s+(.+)", re.I | re.S)
_OPEN_URL = re.compile(r"\bopen\s+(https?://\S+)", re.I)
_OPEN_APP = re.compile(r"\bopen\s+(?:the\s+)?(?:app|application)\s+([^.!\n]+)", re.I)
_LIST = re.compile(r"\b(?:list|show)(?:\s+me)?(?:\s+the)?\s+files\b(?:\s+in\s+([^.!\n]+))?", re.I)
_READ = re.compile(r"\bread(?:\s+the)?\s+file\s+[\"'`]?([^\n\"'`]+)", re.I)
_CALC = re.compile(r"^(?:calculate|compute|what is|what's)\s+([0-9().,+\-*/%\s^a-z]+)$", re.I)
_TIME = re.compile(r"\b(what time|current time|what's the time|what is the time)\b", re.I)
_STATUS = re.compile(r"\b(system status|cpu|memory usage)\b", re.I)
_KNOW = re.compile(r"\b(what do you (?:remember|know)|who am i|what do you know about me)\b", re.I)
_WRITE = re.compile(
    r"(?:write|save|create)(?:\s+a)?(?:\s+file)?(?:\s+called|\s+named)?\s+[\"'`]?([^\s\"'`]+\.[A-Za-z0-9]+)[\"'`]?",
    re.I,
)
_FENCE = re.compile(r"```(?:\w+)?\n([\s\S]*?)```")
_PRINTS = re.compile(r"\bthat prints\s+[\"']?(.+?)[\"']?\s*$", re.I)


_FILE_BLOCK = re.compile(
    r"\[Attached file: ([^\]]+)\]\n(.*?)(?=\n\n\[(?:Attached file:|Image attached)|\Z)",
    re.S,
)


def _split_context(text: str) -> tuple[str, list[tuple[str, str]], str]:
    files = [(name.strip(), body.strip()) for name, body in _FILE_BLOCK.findall(text)]
    image_at = text.find("[Image attached")
    image_note = text[image_at:].strip() if image_at >= 0 else ""
    cut = len(text)
    file_at = text.find("[Attached file:")
    if file_at >= 0:
        cut = min(cut, file_at)
    if image_at >= 0:
        cut = min(cut, image_at)
    return text[:cut].strip(), files, image_note


def _reading(files: list[tuple[str, str]], image_note: str) -> str:
    parts = [f"I read {name}.\n{body[:1200]}" for name, body in files]
    if image_note:
        if "pixels were not sent" in image_note or "not marked as vision-capable" in image_note:
            parts.append(
                "The image is saved. This model cannot see pixels. "
                "Choose a vision model in Settings — GPT-4o, Claude, a Grok vision model, or an Ollama model such as llava — and send the image again."
            )
        else:
            parts.append("The image was included for the vision model.")
    return "\n\n".join(parts)


def plan_offline(user_text: str, memories: list[str] | None = None) -> Plan:
    raw = (user_text or "").strip()
    question, files, image_note = _split_context(raw)
    text = question
    memories = memories or []
    if not text and not files and not image_note:
        return Plan("Say that again, Sahib. The message was empty.")
    if not text and (files or image_note):
        return Plan(_reading(files, image_note))

    match = _REMEMBER.search(text)
    if match:
        fact = " ".join(match.group(1).strip().split())
        return Plan(tool="remember", args={"content": fact, "kind": "explicit"})

    match = _REMIND.search(text)
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        title = " ".join(match.group(3).strip().split())
        factor = 1
        if unit.startswith("minute"):
            factor = 60
        elif unit.startswith("hour"):
            factor = 3600
        return Plan(tool="create_reminder", args={"title": title, "due_in_seconds": amount * factor})

    match = _RUN.search(text)
    if match and not _REMEMBER.search(text):
        command = match.group(1).strip().strip("`")
        return Plan(tool="run_command", args={"command": command})

    match = _OPEN_URL.search(text)
    if match:
        return Plan(tool="open_url", args={"url": match.group(1).rstrip(").,")})

    match = _OPEN_APP.search(text)
    if match:
        return Plan(tool="open_app", args={"name": match.group(1).strip().strip(".")})

    match = _WRITE.search(text)
    if match:
        path = match.group(1)
        fenced = _FENCE.search(text)
        prints = _PRINTS.search(text)
        if fenced:
            content = fenced.group(1)
        elif prints and path.endswith(".py"):
            content = f"print({prints.group(1)!r})\n"
        elif prints:
            content = prints.group(1) + "\n"
        else:
            content = ""
        if content:
            return Plan(tool="write_file", args={"path": path, "content": content})

    match = _LIST.search(text)
    if match:
        directory = (match.group(1) or "sandbox").strip()
        return Plan(tool="list_files", args={"directory": directory})

    match = _READ.search(text)
    if match:
        return Plan(tool="read_file", args={"path": match.group(1).strip()})

    match = _SEARCH.search(text)
    if match:
        return Plan(tool="web_search", args={"query": match.group(1).strip().rstrip(".")})

    match = _CALC.search(text)
    if match and re.search(r"\d", match.group(1)):
        return Plan(tool="calculate", args={"expression": match.group(1).strip()})

    if _TIME.search(text):
        return Plan(tool="get_time", args={})

    if _STATUS.search(text):
        return Plan(tool="get_system_info", args={})

    if _KNOW.search(text):
        if not memories:
            return Plan(
                "I don't have any stored memories yet. Tell me \"remember that …\" and I'll keep it."
            )
        lines = "\n".join(f"- {item}" for item in memories)
        return Plan("Here's what I have on file, Sahib:\n" + lines)

    if files or image_note:
        return Plan(_reading(files, image_note))

    if memories:
        joined = " ".join(memories).lower()
        tokens = [tok for tok in re.findall(r"[a-z0-9']+", text.lower()) if len(tok) > 3]
        hits = [item for item in memories if any(tok in item.lower() for tok in tokens)]
        if hits and any(tok in joined for tok in tokens):
            return Plan(
                "From memory: "
                + " ".join(hits[:2])
                + "\n\nThe offline kernel can act on files, reminders, and commands, but open-ended reasoning needs a model. "
                "Connect OpenAI, Anthropic, xAI, or Ollama in Settings and I'll take it from there."
            )

    return Plan(
        "I heard you, Sahib. This is the offline kernel — it isn't a full language model, so I won't improvise an answer. "
        "Connect OpenAI, Anthropic, xAI, or Ollama in Settings for open-ended reasoning. "
        "I can still remember facts, set reminders, list and read safe-folder files, search when a key is set, "
        "and run a PowerShell or shell command after you approve it."
    )


def memories_from_messages(messages: list[dict[str, Any]]) -> list[str]:
    for message in messages:
        if message.get("role") != "system":
            continue
        content = message.get("content") or ""
        if isinstance(content, list):
            content = "\n".join(part.get("text", "") for part in content if isinstance(part, dict))
        if "Relevant memories:" not in content:
            continue
        section = content.split("Relevant memories:", 1)[1]
        lines = []
        for line in section.splitlines():
            line = line.strip()
            if line.startswith("- "):
                lines.append(line[2:].strip())
            elif line.startswith("Rules:") or line.startswith("Host:"):
                break
        return lines
    return []


def last_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"
            )
    return ""


def trailing_tool_text(messages: list[dict[str, Any]]) -> str | None:
    chunks: list[str] = []
    for message in reversed(messages):
        if message.get("role") == "tool":
            chunks.append(str(message.get("content") or ""))
            continue
        break
    if not chunks:
        return None
    return "\n\n".join(reversed(chunks)).strip()


class OfflineProvider(LLMProvider):
    id = "offline"
    label = "Offline kernel"

    def is_configured(self) -> bool:
        return True

    def status_detail(self) -> str:
        return "Local kernel. No API key. File, memory, reminder, and approved command tools are live."

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str,
    ) -> AsyncIterator[StreamEvent]:
        del tools, model
        followup = trailing_tool_text(messages)
        if followup is not None:
            for piece in _chunks(followup):
                yield StreamEvent.text(piece)
            return
        plan = plan_offline(last_user_text(messages), memories_from_messages(messages))
        if plan.text:
            for piece in _chunks(plan.text):
                yield StreamEvent.text(piece)
        if plan.tool:
            call_id = f"call_{plan.tool}_{uuid.uuid4().hex[:8]}"
            yield StreamEvent.tool(call_id, plan.tool, plan.args or {})


def _chunks(text: str, size: int = 24) -> list[str]:
    if not text:
        return []
    return [text[index : index + size] for index in range(0, len(text), size)]
