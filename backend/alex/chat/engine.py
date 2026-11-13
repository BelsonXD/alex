"""One user turn: retrieve memories, stream a model, run tools, persist everything."""

from __future__ import annotations

import base64
import json
import platform
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from alex.config import DEFAULT_MODELS, get_settings
from alex.database import session_scope
from alex.llm.base import StreamEvent
from alex.llm.providers import get_router, vision_capable
from alex.memory import service as memories
from alex.models import Conversation, Message, Upload, new_id, utcnow
from alex.projects.service import allowlist, safe_folder_list
from alex.tools.builtin import ToolContext, command_is_allowlisted, log_action
from alex.tools.computer import shell_name
from alex.tools.registry import ActionRequest, Registry, ToolResult

Emit = Callable[[dict[str, Any]], Awaitable[None]]
Approve = Callable[[ActionRequest], Awaitable[bool]]

MAX_ROUNDS = 4
IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"}


async def run_turn(
    *,
    content: str,
    conversation_id: str | None,
    project_id: str | None,
    attachment_ids: list[str] | None,
    on_event: Emit,
    approval: Approve,
    registry: Registry,
    source: str = "user",
) -> str:
    attachment_ids = attachment_ids or []
    content = (content or "").strip()
    if not content and not attachment_ids:
        await on_event({"type": "error", "detail": "Message is empty."})
        return ""

    with session_scope() as db:
        convo = _conversation(db, conversation_id, project_id, content or "Attachment")
        settings_row = _settings(db)
        excerpts, images = _load_attachments(db, attachment_ids)
        user_text = _compose_user_text(content, excerpts, images, settings_row.provider, settings_row.model)
        memories.store_extracted(db, content, source="conversation")
        meta = {"attachments": attachment_ids, "source": source}
        db.add(
            Message(
                conversation_id=convo.id,
                role="user",
                content=user_text,
                metadata_json=json.dumps(meta),
            )
        )
        if convo.title in {"", "New conversation"}:
            convo.title = _title(content or excerpts[0][0] if excerpts else "Attachment")
        convo.updated_at = utcnow()
        db.flush()
        conversation_id = convo.id
        title = convo.title
        provider_name = settings_row.provider or "offline"
        model = (settings_row.model or "").strip() or DEFAULT_MODELS.get(provider_name, "")
        persona_name = settings_row.assistant_name
        persona = settings_row.persona
        folders = safe_folder_list(settings_row)
        allowed = allowlist(settings_row)
        project_folder = Path(convo.project.folder) if convo.project and convo.project.folder else None
        bound_project = convo.project_id
        recalled = memories.retrieve(db, content or user_text, k=5)
        memory_lines = [row.content for row in recalled]
        history = _history(db, convo.id)
        search_provider = settings_row.search_provider
        sandbox = next((folder for folder in folders if folder.name == "sandbox"), folders[0] if folders else None)

    await on_event({"type": "conversation", "conversation_id": conversation_id, "title": title})
    await on_event({"type": "status", "state": "thinking", "conversation_id": conversation_id})

    provider = get_router().get(provider_name)
    system = _system_prompt(persona_name, persona, memory_lines, folders, provider_name, model)
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    messages.extend(history[:-1])
    send_images = images if vision_capable(provider_name, model) else []
    messages.append(_current_user_message(user_text, send_images))

    ctx = ToolContext(
        db_factory=session_scope,
        safe_folders=folders,
        allowlist=allowed,
        system_name=platform.system(),
        search_provider=search_provider,
        tavily_api_key=get_settings().tavily_api_key,
        brave_api_key=get_settings().brave_search_api_key,
        project_id=bound_project,
        workspace=project_folder,
        sandbox=sandbox,
    )

    assistant_text = ""
    for _round in range(MAX_ROUNDS):
        text_parts: list[str] = []
        calls: list[dict[str, Any]] = []
        async for event in provider.stream(messages, registry.schemas(), model):
            if event.kind == "error":
                await on_event({"type": "error", "conversation_id": conversation_id, "detail": event.text})
                await on_event({"type": "status", "state": "idle", "conversation_id": conversation_id})
                _save_assistant(conversation_id, "".join(text_parts), [])
                return "".join(text_parts)
            if event.kind == "text" and event.text:
                text_parts.append(event.text)
                assistant_text += event.text
                await on_event({"type": "token", "conversation_id": conversation_id, "text": event.text})
            elif event.kind == "tool_call":
                calls.append({"id": event.call_id, "name": event.name, "arguments": event.arguments})
                await on_event(
                    {
                        "type": "tool",
                        "conversation_id": conversation_id,
                        "call_id": event.call_id,
                        "name": event.name,
                        "arguments": event.arguments,
                    }
                )
        visible = "".join(text_parts)
        if not calls:
            _save_assistant(conversation_id, visible, [])
            await on_event({"type": "done", "conversation_id": conversation_id, "text": visible})
            await on_event({"type": "status", "state": "idle", "conversation_id": conversation_id})
            return assistant_text

        messages.append({"role": "assistant", "content": visible, "tool_calls": calls})
        _save_assistant(conversation_id, visible, calls)
        for call in calls:
            result = await execute_tool(call["name"], call["arguments"], ctx, approval, registry)
            messages.append(
                {"role": "tool", "tool_call_id": call["id"], "name": call["name"], "content": result.output}
            )
            _save_tool(conversation_id, call, result)
            await on_event(
                {
                    "type": "tool_result",
                    "conversation_id": conversation_id,
                    "call_id": call["id"],
                    "name": call["name"],
                    "ok": result.ok,
                    "output": result.output,
                    "sources": result.sources,
                }
            )
        await on_event({"type": "status", "state": "thinking", "conversation_id": conversation_id})

    note = "\n\nI stopped after several tool rounds so this turn couldn't loop forever."
    _save_assistant(conversation_id, note.strip(), [])
    await on_event({"type": "token", "conversation_id": conversation_id, "text": note})
    await on_event({"type": "done", "conversation_id": conversation_id, "text": note.strip()})
    await on_event({"type": "status", "state": "idle", "conversation_id": conversation_id})
    return assistant_text + note


async def execute_tool(
    name: str,
    args: dict[str, Any],
    ctx: ToolContext,
    approval: Approve,
    registry: Registry,
) -> ToolResult:
    spec = registry.get(name)
    if spec is None:
        return ToolResult(False, f"Unknown tool: {name}")
    needs = spec.needs_approval
    if name == "run_command" and command_is_allowlisted(str(args.get("command") or ""), ctx.allowlist):
        needs = False
    if needs:
        request = ActionRequest(
            tool=name,
            summary=_summary(name, args),
            arguments=args,
            risk=_risk(name, ctx.system_name),
        )
        approved = await approval(request)
        if not approved:
            with ctx.db_factory() as db:
                log_action(db, name, args, "denied", "Denied by Sahib. Not executed.")
            return ToolResult(False, "Sahib denied this action. It was not executed.")
    try:
        result = await spec.handler(args or {}, ctx)
    except Exception as exc:  # noqa: BLE001 — surface tool failures to the chat
        result = ToolResult(False, f"{type(exc).__name__}: {exc}")
    with ctx.db_factory() as db:
        log_action(db, name, args or {}, "executed" if result.ok else "failed", result.output)
    return result


def _summary(name: str, args: dict[str, Any]) -> str:
    if name == "run_command":
        cwd = args.get("cwd") or "(safe folder)"
        return f"{args.get('command', '')}\n\nWorking directory: {cwd}"
    if name == "write_file":
        preview = str(args.get("content") or "")
        if len(preview) > 1200:
            preview = preview[:1200] + "\n…"
        return f"Write {args.get('path')}\n\n{preview}"
    if name in {"delete_file", "read_file"}:
        return str(args.get("path") or "")
    if name == "move_file":
        return f"{args.get('source')}  →  {args.get('destination')}"
    if name == "organize_files":
        return f"In {args.get('directory')}, move {args.get('pattern')} into {args.get('destination')}"
    if name == "open_app":
        return str(args.get("name") or "")
    if name == "open_url":
        return str(args.get("url") or "")
    return json.dumps(args, default=str)[:800]


def _risk(name: str, system_name: str) -> str:
    if name == "run_command":
        return f"This runs in {shell_name(system_name)} as your user account on this computer."
    if name in {"write_file", "move_file", "delete_file", "organize_files"}:
        return "This changes files, and only inside your safe folders."
    if name in {"open_app", "open_url"}:
        return "This opens a program or a website on this computer."
    return "This action waits for your approval."


def _settings(db: Session):
    from alex.models import AppSetting

    row = db.get(AppSetting, 1)
    if row is None:
        raise RuntimeError("Settings were not initialized.")
    return row


def _conversation(db: Session, conversation_id: str | None, project_id: str | None, content: str) -> Conversation:
    if conversation_id:
        convo = db.get(Conversation, conversation_id)
        if convo is not None:
            return convo
    convo = Conversation(id=new_id(), title=_title(content) if content else "New conversation", project_id=project_id)
    db.add(convo)
    db.flush()
    return convo


def _history(db: Session, conversation_id: str) -> list[dict[str, Any]]:
    rows = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
        .all()
    )
    rows = rows[-30:]
    built = []
    for row in rows:
        message: dict[str, Any] = {"role": row.role, "content": row.content}
        if row.role == "tool":
            message["tool_call_id"] = row.tool_call_id
            message["name"] = row.tool_name
        try:
            meta = json.loads(row.metadata_json or "{}")
        except json.JSONDecodeError:
            meta = {}
        if meta.get("tool_calls"):
            message["tool_calls"] = meta["tool_calls"]
        built.append(message)
    return built


def _save_assistant(conversation_id: str, content: str, calls: list[dict[str, Any]]) -> None:
    with session_scope() as db:
        convo = db.get(Conversation, conversation_id)
        if convo is not None:
            convo.updated_at = utcnow()
        db.add(
            Message(
                conversation_id=conversation_id,
                role="assistant",
                content=content or "",
                metadata_json=json.dumps({"tool_calls": calls} if calls else {}),
            )
        )


def _save_tool(conversation_id: str, call: dict[str, Any], result: ToolResult) -> None:
    with session_scope() as db:
        db.add(
            Message(
                conversation_id=conversation_id,
                role="tool",
                content=result.output[:8000],
                tool_name=call.get("name"),
                tool_call_id=call.get("id"),
                metadata_json=json.dumps({"ok": result.ok, "sources": result.sources}),
            )
        )


def _title(text: str) -> str:
    line = " ".join((text or "").strip().split())
    if not line:
        return "New conversation"
    return line[:48] + ("…" if len(line) > 48 else "")


def _system_prompt(
    name: str,
    persona: str,
    memory_lines: list[str],
    folders: list[Path],
    provider_name: str,
    model: str,
) -> str:
    folder_text = "\n".join(f"- {folder}" for folder in folders) or "- (none)"
    memory_text = "\n".join(f"- {line}" for line in memory_lines) or "- (none yet)"
    shell = shell_name()
    return (
        f"You are {name}.\n{persona}\n\n"
        f"Host: {platform.platform()}\n"
        f"Shell for run_command: {shell}. Use {shell} syntax.\n"
        f"Active provider: {provider_name} / {model}\n"
        f"Vision for this model: {'yes' if vision_capable(provider_name, model) else 'no'}\n\n"
        f"Safe folders:\n{folder_text}\n\n"
        f"Relevant memories:\n{memory_text}\n\n"
        "Rules:\n"
        "- Use tools for anything that reads or changes the computer. Never claim a command ran or a file changed unless the tool result says so.\n"
        "- run_command, write_file, move_file, delete_file, organize_files, open_app, and open_url ask Sahib before they execute. Call them when they are the right action.\n"
        "- On Windows, commands are PowerShell. Paths may be drive-letter paths.\n"
        "- Cite web_search sources by URL.\n"
        "- When Sahib states a lasting fact about himself, call remember.\n"
        "- If a tool says a key is not configured, tell him which key and stop. Do not invent search results or file contents.\n"
    )


def _compose_user_text(
    content: str,
    excerpts: list[tuple[str, str]],
    images: list[dict[str, str]],
    provider: str,
    model: str,
) -> str:
    parts = [content] if content else []
    for filename, excerpt in excerpts:
        parts.append(f"[Attached file: {filename}]\n{excerpt}")
    if images and not vision_capable(provider, model or DEFAULT_MODELS.get(provider, "")):
        names = ", ".join(image["filename"] for image in images)
        parts.append(
            f"[Image attached: {names}. This model is not marked as vision-capable, "
            "so the pixels were not sent. Switch to a vision model in Settings to analyze images.]"
        )
    elif images:
        names = ", ".join(image["filename"] for image in images)
        parts.append(f"[Image attached and sent to the model: {names}]")
    return "\n\n".join(part for part in parts if part).strip()


def _current_user_message(user_text: str, images: list[dict[str, str]]) -> dict[str, Any]:
    if not images:
        return {"role": "user", "content": user_text}
    parts: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
    for image in images:
        parts.append({"type": "image", "mime": image["mime"], "data": image["data"]})
    return {"role": "user", "content": parts}


def _load_attachments(db: Session, attachment_ids: list[str]) -> tuple[list[tuple[str, str]], list[dict[str, str]]]:
    excerpts: list[tuple[str, str]] = []
    images: list[dict[str, str]] = []
    for attachment_id in attachment_ids:
        row = db.get(Upload, attachment_id)
        if row is None:
            continue
        if row.kind == "image":
            path = Path(row.path)
            if path.exists() and path.stat().st_size <= 4_000_000:
                images.append(
                    {
                        "filename": row.filename,
                        "mime": row.mime,
                        "data": base64.b64encode(path.read_bytes()).decode("ascii"),
                    }
                )
            continue
        if row.text_excerpt:
            excerpts.append((row.filename, row.text_excerpt[:12000]))
    return excerpts, images
