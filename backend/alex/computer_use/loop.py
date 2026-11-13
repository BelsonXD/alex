"""Vision loop: look at the screen, choose one action, repeat until done or stopped."""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Awaitable, Callable
from typing import Any

from alex.computer_use.desktop import capture_screen, perform_action
from alex.computer_use.safety import sensitivity
from alex.config import KEY_HELP
from alex.llm.providers import vision_capable

Decide = Callable[..., Awaitable[dict[str, Any]]]
Emit = Callable[[dict[str, Any]], Awaitable[None]]
Approve = Callable[..., Awaitable[bool]]


async def run_computer_task(
    *,
    goal: str,
    on_event: Emit,
    approval: Approve,
    stop_event: threading.Event,
    enabled: bool,
    max_steps: int,
    provider_name: str,
    model: str,
    provider: Any,
    capture: Callable[[], dict[str, Any]] | None = None,
    act: Callable[[dict[str, Any], dict[str, Any], threading.Event], str] | None = None,
    decide: Decide | None = None,
) -> None:
    if not enabled:
        await on_event(
            {
                "type": "error",
                "detail": "Screen control is off. Turn on Computer use in Settings, then start the task again.",
            }
        )
        return
    if not vision_capable(provider_name, model) or provider_name == "offline":
        await on_event(
            {
                "type": "error",
                "detail": (
                    "Screen control needs a vision model. In Settings choose OpenAI gpt-4o, "
                    f"Anthropic Claude, or xAI Grok, and add the key ({KEY_HELP['openai']}, "
                    f"{KEY_HELP['anthropic']}, or {KEY_HELP['xai']})."
                ),
            }
        )
        return
    if not provider.is_configured():
        await on_event({"type": "error", "detail": provider.status_detail()})
        return

    from alex.tools.registry import ActionRequest

    allowed = await approval(
        ActionRequest(
            tool="computer_use",
            summary=goal,
            arguments={"goal": goal},
            risk="ALEX will see your screen and move the mouse and keyboard until you press Stop or Ctrl+Alt+Esc.",
        )
    )
    if not allowed:
        await on_event({"type": "computer_done", "summary": "Sahib did not start screen control."})
        return

    capture_fn = capture or capture_screen
    act_fn = act or perform_action
    decide_fn = decide or _decide
    history: list[str] = []
    steps = max(1, min(int(max_steps or 12), 40))
    for step in range(1, steps + 1):
        if stop_event.is_set():
            await on_event({"type": "computer_done", "summary": "Stopped."})
            return
        frame = capture_fn()
        await on_event(
            {
                "type": "computer_frame",
                "step": step,
                "image": frame.get("b64") or "",
                "image_width": frame.get("image_width"),
                "image_height": frame.get("image_height"),
                "screen_width": frame.get("screen_width"),
                "screen_height": frame.get("screen_height"),
                "dpi_scale": frame.get("dpi_scale"),
            }
        )
        try:
            action = await decide_fn(provider, model, goal, history, frame)
        except Exception as exc:  # noqa: BLE001
            await on_event({"type": "error", "detail": f"The vision model did not answer: {exc}"})
            return
        kind = str(action.get("action") or "")
        reason = str(action.get("reason") or "")
        if kind in {"done", "fail"}:
            await on_event(
                {
                    "type": "computer_action",
                    "step": step,
                    "action": kind,
                    "reason": reason,
                    "summary": action.get("summary") or reason,
                    "ok": kind == "done",
                }
            )
            await on_event({"type": "computer_done", "summary": action.get("summary") or reason or kind})
            return
        sensitive, why = sensitivity(action)
        if sensitive:
            ok = await approval(
                ActionRequest(
                    tool="computer_use_step",
                    summary=f"{kind}: {action.get('text') or action.get('keys') or reason}",
                    arguments=action,
                    risk=why + " Nothing is typed or clicked until you approve this step.",
                )
            )
            if not ok or stop_event.is_set():
                history.append(f"Step {step} denied: {why}")
                await on_event(
                    {
                        "type": "computer_action",
                        "step": step,
                        "action": kind,
                        "reason": why,
                        "ok": False,
                        "summary": "Denied. Not performed.",
                    }
                )
                continue
        if stop_event.is_set():
            await on_event({"type": "computer_done", "summary": "Stopped."})
            return
        try:
            result = act_fn(action, frame, stop_event)
            ok = True
        except Exception as exc:  # noqa: BLE001
            result = f"{type(exc).__name__}: {exc}"
            ok = False
            if "FailSafe" in type(exc).__name__:
                stop_event.set()
        history.append(f"Step {step} {kind} ({reason}) -> {result}")
        await on_event(
            {
                "type": "computer_action",
                "step": step,
                "action": kind,
                "reason": reason,
                "summary": result,
                "ok": ok,
                "arguments": {key: action.get(key) for key in ("x", "y", "text", "keys", "button") if key in action},
            }
        )
        if stop_event.is_set():
            await on_event({"type": "computer_done", "summary": "Stopped."})
            return
    await on_event({"type": "computer_done", "summary": f"Stopped after {steps} steps so the loop could not run forever."})


async def _decide(provider: Any, model: str, goal: str, history: list[str], frame: dict[str, Any]) -> dict[str, Any]:
    prompt = (
        f"Goal: {goal}\n"
        f"Screenshot size: {frame['image_width']} x {frame['image_height']} pixels. "
        "Return coordinates in that image, origin top-left.\n"
        "Previous steps:\n"
        + ("\n".join(history[-8:]) or "(none)")
        + "\nReply with one JSON object only. Actions: move, click, drag, scroll, type, hotkey, key, wait, done, fail.\n"
        'Examples: {"action":"click","x":120,"y":40,"button":"left","reason":"focus the address bar"}\n'
        '{"action":"type","text":"hello","reason":"enter the query","sensitive":false}\n'
        '{"action":"hotkey","keys":["ctrl","l"],"reason":"focus location"}\n'
        '{"action":"scroll","x":400,"y":300,"dy":-3,"reason":"scroll down"}\n'
        '{"action":"drag","x":10,"y":10,"x2":80,"y2":40,"reason":"select"}\n'
        '{"action":"done","summary":"the file is open"}\n'
        "Set sensitive true before typing a password, paying, sending a message, or deleting."
    )
    messages = [
        {
            "role": "system",
            "content": "You control Sahib's Windows desktop one step at a time. You only output JSON. You never invent that a click happened.",
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image", "mime": "image/jpeg", "data": frame["b64"]},
            ],
        },
    ]
    chunks: list[str] = []
    async for event in provider.stream(messages, [], model):
        if event.kind == "error":
            raise RuntimeError(event.text)
        if event.kind == "text" and event.text:
            chunks.append(event.text)
    return parse_action("".join(chunks))


def parse_action(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S)
    if fenced:
        raw = fenced.group(1)
    else:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]
    data = json.loads(raw)
    if not isinstance(data, dict) or "action" not in data:
        raise ValueError("The model did not return an action.")
    return data
