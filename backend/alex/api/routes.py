"""REST routes and the chat websocket."""

from __future__ import annotations

import asyncio
import json
import logging
import platform
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import psutil
from fastapi import APIRouter, FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from alex import __version__
from alex.config import KEY_HELP, MODEL_CHOICES, apply_runtime_keys, get_settings
from alex.database import session_scope
from alex.models import (
    ActionLog,
    AppSetting,
    Automation,
    Conversation,
    Message,
    Notification,
    Project,
    Reminder,
    Upload,
    new_id,
    utcnow,
)
from alex.chat.engine import run_turn
from alex.memory import service as memory_service
from alex.memory.embeddings import describe_backend
from alex.projects.service import allowlist, create_project, delete_project, list_folder, safe_folder_list
from alex.tools.computer import build_open_folder_argv, expand_user_path, format_process, run_process, shell_name
from alex.tools.registry import ActionRequest
from alex.voice.service import NotConfigured, capabilities, stream_tts, transcribe

log = logging.getLogger("alex.api")
router = APIRouter()

TEXT_SUFFIXES = {
    ".txt", ".md", ".csv", ".json", ".py", ".ts", ".tsx", ".js", ".jsx", ".html",
    ".css", ".yml", ".yaml", ".toml", ".log", ".ps1", ".bat", ".sh", ".xml",
}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


class SettingsIn(BaseModel):
    assistant_name: str | None = None
    persona: str | None = None
    provider: str | None = None
    model: str | None = None
    voice_provider: str | None = None
    voice_id: str | None = None
    auto_speak: bool | None = None
    search_provider: str | None = None
    safe_folders: list[str] | None = None
    command_allowlist: list[str] | None = None
    computer_use_enabled: bool | None = None
    computer_use_max_steps: int | None = None
    voice_wake: bool | None = None
    wake_phrase: str | None = None
    alex_github_repo: str | None = None
    alex_update_manifest: str | None = None


class SecretsIn(BaseModel):
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    xai_api_key: str | None = None
    elevenlabs_api_key: str | None = None
    elevenlabs_voice_id: str | None = None
    tavily_api_key: str | None = None
    brave_search_api_key: str | None = None
    ollama_base_url: str | None = None
    alex_update_token: str | None = None


class MemoryIn(BaseModel):
    content: str
    kind: str = "fact"


class MemoryUpdate(BaseModel):
    content: str
    kind: str | None = None


class ProjectIn(BaseModel):
    name: str
    description: str = ""


class ConversationIn(BaseModel):
    title: str | None = None
    project_id: str | None = None


class ReminderIn(BaseModel):
    title: str
    notes: str = ""
    due_at: str | None = None
    due_in_seconds: int | None = None


class AutomationIn(BaseModel):
    name: str
    prompt: str
    interval_seconds: int = 3600
    enabled: bool = True


class AutomationPatch(BaseModel):
    name: str | None = None
    prompt: str | None = None
    interval_seconds: int | None = None
    enabled: bool | None = None


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class DecisionIn(BaseModel):
    approved: bool


def register_routes(app: FastAPI) -> None:
    app.include_router(router, prefix="/api")

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
        await _websocket(websocket)


@router.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "name": "ALEX", "version": __version__}


@router.get("/system/update")
async def update_status(request: Request) -> dict[str, Any]:
    from alex.updates.service import check_for_update

    status = await check_for_update()
    request.app.state.update_status = status
    return status


@router.post("/system/update/apply")
async def update_apply() -> dict[str, Any]:
    import os

    from alex.updates.service import apply_zip, check_for_update, download_zip

    status = await check_for_update()
    if not status.get("update_available"):
        raise HTTPException(400, status.get("detail") or "No update is available.")
    settings = get_settings()
    archive = settings.data_path / "updates" / f"alex-{status['latest']}.zip"
    await download_zip(status["zip_url"], archive, settings.alex_update_token, status.get("sha256") or "")
    try:
        result = apply_zip(archive, restart=True)
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)) from exc

    async def _exit_after_response() -> None:
        await asyncio.sleep(1)
        os._exit(0)

    asyncio.create_task(_exit_after_response())
    return result


@router.get("/computer/status")
def computer_status(request: Request) -> dict[str, Any]:
    from alex.computer_use.desktop import prepare_windows_dpi

    with session_scope() as db:
        row = _settings(db)
        enabled = bool(getattr(row, "computer_use_enabled", False))
    return {
        "enabled": enabled,
        "running": bool(getattr(request.app.state, "computer_running", False)),
        "hotkey": "Ctrl+Alt+Esc",
        "dpi_scale": prepare_windows_dpi(),
    }


@router.get("/computer/preview")
def computer_preview() -> dict[str, Any]:
    from alex.computer_use.desktop import capture_screen

    try:
        frame = capture_screen()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"Could not capture the screen: {exc}") from exc
    return {
        "image": frame["b64"],
        "image_width": frame["image_width"],
        "image_height": frame["image_height"],
        "screen_width": frame["screen_width"],
        "screen_height": frame["screen_height"],
        "dpi_scale": frame["dpi_scale"],
    }


@router.post("/computer/stop")
def computer_stop(request: Request) -> dict[str, bool]:
    request.app.state.computer_stop.set()
    request.app.state.computer_running = False
    return {"ok": True}


@router.get("/system/status")
def system_status(request: Request) -> dict[str, Any]:
    live = request.app
    settings = get_settings()
    with session_scope() as db:
        row = _settings(db)
        from alex.llm.providers import get_router

        current = get_router().get(row.provider)
        vm = psutil.virtual_memory()
        disk = shutil.disk_usage(settings.data_path)
        return {
            "ok": True,
            "version": __version__,
            "platform": platform.platform(),
            "system": platform.system(),
            "python": platform.python_version(),
            "shell": shell_name(),
            "cpu_percent": psutil.cpu_percent(interval=0.05),
            "memory_percent": vm.percent,
            "memory_used_mb": vm.used // (1024 * 1024),
            "memory_total_mb": vm.total // (1024 * 1024),
            "disk_percent": round(disk.used / disk.total * 100, 1) if disk.total else 0,
            "uptime_seconds": round(max(0.0, __import__("time").time() - live.state.started), 1),
            "provider": row.provider,
            "provider_label": current.label,
            "provider_configured": current.is_configured(),
            "provider_detail": current.status_detail(),
            "model": row.model,
            "assistant_name": row.assistant_name,
            "tools": live.state.registry.public_list(),
            "plugins": live.state.plugins,
            "safe_folders": [str(folder) for folder in safe_folder_list(row)],
            "data_dir": str(settings.data_path),
            "embeddings": describe_backend(settings.openai_api_key),
            "keys": _key_status(),
        }


@router.post("/system/probe")
async def probe_provider() -> dict[str, Any]:
    from alex.llm.providers import get_router

    with session_scope() as db:
        row = _settings(db)
        provider_name = row.provider
        model = row.model or ""
    from alex.config import DEFAULT_MODELS

    model = model or DEFAULT_MODELS.get(provider_name, "")
    provider = get_router().get(provider_name)
    result = await provider.probe(model)
    result["provider"] = provider_name
    result["model"] = model
    return result


@router.get("/tools")
def tools(request: Request) -> list[dict[str, Any]]:
    return request.app.state.registry.public_list()


@router.get("/settings")
def get_settings_route() -> dict[str, Any]:
    with session_scope() as db:
        return _settings_payload(db)


@router.put("/settings")
def update_settings(body: SettingsIn) -> dict[str, Any]:
    from alex.llm.providers import get_router

    with session_scope() as db:
        row = _settings(db)
        data = body.model_dump(exclude_unset=True)
        if "provider" in data:
            if data["provider"] not in get_router().providers:
                raise HTTPException(400, f"Unknown provider '{data['provider']}'.")
            row.provider = data["provider"]
        if "assistant_name" in data:
            name = (data["assistant_name"] or "").strip()
            if not name:
                raise HTTPException(400, "Name cannot be empty.")
            row.assistant_name = name[:80]
        if "persona" in data:
            row.persona = data["persona"] or ""
        if "model" in data:
            row.model = (data["model"] or "").strip()[:120]
        if "voice_provider" in data:
            if data["voice_provider"] not in {"browser", "openai", "elevenlabs"}:
                raise HTTPException(400, "Voice provider must be browser, openai, or elevenlabs.")
            row.voice_provider = data["voice_provider"]
        if "voice_id" in data:
            row.voice_id = (data["voice_id"] or "").strip()[:200]
        if "auto_speak" in data:
            row.auto_speak = bool(data["auto_speak"])
        if "search_provider" in data:
            if data["search_provider"] not in {"auto", "tavily", "brave", "none"}:
                raise HTTPException(400, "Search provider must be auto, tavily, brave, or none.")
            row.search_provider = data["search_provider"]
        if "safe_folders" in data:
            row.safe_folders = json.dumps(_normalize_folders(data["safe_folders"] or []))
        if "command_allowlist" in data:
            row.command_allowlist = json.dumps(_normalize_allowlist(data["command_allowlist"] or []))
        if "computer_use_enabled" in data:
            row.computer_use_enabled = bool(data["computer_use_enabled"])
        if "computer_use_max_steps" in data:
            row.computer_use_max_steps = max(1, min(40, int(data["computer_use_max_steps"] or 12)))
        if "voice_wake" in data:
            row.voice_wake = bool(data["voice_wake"])
        if "wake_phrase" in data:
            phrase = (data["wake_phrase"] or "alex").strip().lower()[:80]
            row.wake_phrase = phrase or "alex"
        if "alex_github_repo" in data or "alex_update_manifest" in data:
            from alex.config import apply_runtime_keys

            secret_updates = {}
            if "alex_github_repo" in data:
                secret_updates["alex_github_repo"] = (data["alex_github_repo"] or "").strip()
            if "alex_update_manifest" in data:
                secret_updates["alex_update_manifest"] = (data["alex_update_manifest"] or "").strip()
            apply_runtime_keys(secret_updates)
        db.add(row)
        db.flush()
        return _settings_payload(db)


@router.post("/settings/secrets")
def update_secrets(body: SecretsIn) -> dict[str, Any]:
    updates = {key: value for key, value in body.model_dump().items() if value is not None}
    apply_runtime_keys(updates)
    return {"ok": True, "keys": _key_status()}


@router.get("/conversations")
def list_conversations() -> list[dict[str, Any]]:
    with session_scope() as db:
        rows = db.query(Conversation).order_by(Conversation.updated_at.desc()).all()
        return [_conversation_dict(row) for row in rows]


@router.post("/conversations")
def create_conversation(body: ConversationIn) -> dict[str, Any]:
    with session_scope() as db:
        if body.project_id and db.get(Project, body.project_id) is None:
            raise HTTPException(404, "Project not found.")
        row = Conversation(
            title=(body.title or "New conversation")[:200],
            project_id=body.project_id,
        )
        db.add(row)
        db.flush()
        return _conversation_dict(row)


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str) -> dict[str, bool]:
    with session_scope() as db:
        row = db.get(Conversation, conversation_id)
        if row is None:
            raise HTTPException(404, "Conversation not found.")
        db.delete(row)
        return {"ok": True}


@router.get("/conversations/{conversation_id}/messages")
def list_messages(conversation_id: str) -> list[dict[str, Any]]:
    with session_scope() as db:
        if db.get(Conversation, conversation_id) is None:
            raise HTTPException(404, "Conversation not found.")
        rows = (
            db.query(Message)
            .filter(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
            .all()
        )
        return [_message_dict(row) for row in rows]


@router.get("/memories")
def list_memories(q: str = "") -> list[dict[str, Any]]:
    with session_scope() as db:
        return [memory_service.as_dict(row) for row in memory_service.list_memories(db, q)]


@router.post("/memories")
def create_memory(body: MemoryIn) -> dict[str, Any]:
    with session_scope() as db:
        try:
            row = memory_service.remember(db, body.content, kind=body.kind or "fact", source="manual")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return memory_service.as_dict(row)


@router.put("/memories/{memory_id}")
def update_memory(memory_id: str, body: MemoryUpdate) -> dict[str, Any]:
    with session_scope() as db:
        row = memory_service.update_memory(db, memory_id, body.content, body.kind)
        if row is None:
            raise HTTPException(404, "Memory not found.")
        return memory_service.as_dict(row)


@router.delete("/memories/{memory_id}")
def remove_memory(memory_id: str) -> dict[str, bool]:
    with session_scope() as db:
        if not memory_service.delete_memory(db, memory_id):
            raise HTTPException(404, "Memory not found.")
        return {"ok": True}


@router.get("/projects")
def list_projects() -> list[dict[str, Any]]:
    with session_scope() as db:
        rows = db.query(Project).order_by(Project.created_at.desc()).all()
        return [_project_dict(row, db) for row in rows]


@router.post("/projects")
def add_project(body: ProjectIn) -> dict[str, Any]:
    with session_scope() as db:
        try:
            row = create_project(db, body.name, body.description)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return _project_dict(row, db)


@router.delete("/projects/{project_id}")
def remove_project(project_id: str, delete_files: bool = False) -> dict[str, bool]:
    with session_scope() as db:
        row = db.get(Project, project_id)
        if row is None:
            raise HTTPException(404, "Project not found.")
        for convo in list(row.conversations):
            convo.project_id = None
        delete_project(db, row, delete_files)
        return {"ok": True}


@router.get("/projects/{project_id}/files")
def project_files(project_id: str) -> dict[str, Any]:
    with session_scope() as db:
        row = db.get(Project, project_id)
        if row is None:
            raise HTTPException(404, "Project not found.")
        folder = Path(row.folder)
        return {"project": _project_dict(row, db), "files": list_folder(folder)}


@router.post("/projects/{project_id}/open")
def open_project(project_id: str) -> dict[str, Any]:
    with session_scope() as db:
        row = db.get(Project, project_id)
        if row is None:
            raise HTTPException(404, "Project not found.")
        folder = row.folder
        system = platform.system()
    try:
        proc = run_process(build_open_folder_argv(folder, system), None, 15, system)
        ok, detail = format_process(proc)
    except Exception as exc:  # noqa: BLE001 — file managers are optional on headless hosts
        ok, detail = False, str(exc)
    with session_scope() as db:
        db.add(
            ActionLog(
                tool_name="open_folder",
                arguments_json=json.dumps({"path": folder}),
                status="executed" if ok else "failed",
                result=detail[:4000],
            )
        )
    return {"ok": ok, "path": folder, "detail": detail}


@router.get("/reminders")
def list_reminders() -> list[dict[str, Any]]:
    with session_scope() as db:
        rows = db.query(Reminder).order_by(Reminder.due_at.asc()).all()
        return [_reminder_dict(row) for row in rows]


@router.post("/reminders")
def add_reminder(body: ReminderIn) -> dict[str, Any]:
    title = body.title.strip()
    if not title:
        raise HTTPException(400, "Title is required.")
    due = _parse_due(body.due_at, body.due_in_seconds)
    with session_scope() as db:
        row = Reminder(title=title[:300], notes=body.notes, due_at=due, status="pending")
        db.add(row)
        db.flush()
        return _reminder_dict(row)


@router.post("/reminders/{reminder_id}/complete")
def complete_reminder(reminder_id: str) -> dict[str, Any]:
    with session_scope() as db:
        row = db.get(Reminder, reminder_id)
        if row is None:
            raise HTTPException(404, "Reminder not found.")
        row.status = "done"
        db.add(row)
        db.flush()
        return _reminder_dict(row)


@router.delete("/reminders/{reminder_id}")
def delete_reminder(reminder_id: str) -> dict[str, bool]:
    with session_scope() as db:
        row = db.get(Reminder, reminder_id)
        if row is None:
            raise HTTPException(404, "Reminder not found.")
        db.delete(row)
        return {"ok": True}


@router.get("/automations")
def list_automations() -> list[dict[str, Any]]:
    with session_scope() as db:
        rows = db.query(Automation).order_by(Automation.created_at.desc()).all()
        return [_automation_dict(row) for row in rows]


@router.post("/automations")
def add_automation(body: AutomationIn) -> dict[str, Any]:
    name = body.name.strip()
    prompt = body.prompt.strip()
    if not name or not prompt:
        raise HTTPException(400, "Name and prompt are required.")
    interval = max(30, int(body.interval_seconds))
    with session_scope() as db:
        row = Automation(
            name=name[:200],
            prompt=prompt,
            interval_seconds=interval,
            enabled=body.enabled,
            next_run_at=utcnow() + timedelta(seconds=interval),
        )
        db.add(row)
        db.flush()
        return _automation_dict(row)


@router.put("/automations/{automation_id}")
def patch_automation(automation_id: str, body: AutomationPatch) -> dict[str, Any]:
    with session_scope() as db:
        row = db.get(Automation, automation_id)
        if row is None:
            raise HTTPException(404, "Automation not found.")
        if body.name is not None:
            row.name = body.name.strip()[:200] or row.name
        if body.prompt is not None:
            row.prompt = body.prompt
        if body.interval_seconds is not None:
            row.interval_seconds = max(30, int(body.interval_seconds))
        if body.enabled is not None:
            row.enabled = body.enabled
            if body.enabled and row.next_run_at is None:
                row.next_run_at = utcnow() + timedelta(seconds=row.interval_seconds)
        db.add(row)
        db.flush()
        return _automation_dict(row)


@router.delete("/automations/{automation_id}")
def delete_automation(automation_id: str) -> dict[str, bool]:
    with session_scope() as db:
        row = db.get(Automation, automation_id)
        if row is None:
            raise HTTPException(404, "Automation not found.")
        db.delete(row)
        return {"ok": True}


@router.post("/automations/{automation_id}/run")
async def run_automation_now(automation_id: str, request: Request) -> dict[str, Any]:
    from alex.automations.scheduler import _run_automation

    with session_scope() as db:
        row = db.get(Automation, automation_id)
        if row is None:
            raise HTTPException(404, "Automation not found.")
    note = await _run_automation(request.app, automation_id)
    with session_scope() as db:
        row = db.get(Automation, automation_id)
        payload = _automation_dict(row) if row else {}
    payload["notification"] = note
    return payload


@router.get("/actions")
def list_actions() -> list[dict[str, Any]]:
    with session_scope() as db:
        rows = db.query(ActionLog).order_by(ActionLog.created_at.desc()).limit(80).all()
        return [
            {
                "id": row.id,
                "tool_name": row.tool_name,
                "arguments": _loads(row.arguments_json),
                "status": row.status,
                "result": row.result,
                "created_at": _iso(row.created_at),
            }
            for row in rows
        ]


@router.get("/notifications")
def list_notifications() -> list[dict[str, Any]]:
    with session_scope() as db:
        rows = db.query(Notification).order_by(Notification.created_at.desc()).limit(50).all()
        return [_notification_dict(row) for row in rows]


@router.post("/notifications/read")
def read_notifications() -> dict[str, bool]:
    with session_scope() as db:
        for row in db.query(Notification).filter(Notification.read.is_(False)).all():
            row.read = True
        return {"ok": True}


@router.post("/uploads")
async def upload_file(file: UploadFile = File(...)) -> dict[str, Any]:
    raw_name = file.filename or "upload"
    safe = _safe_name(raw_name)
    data = await file.read()
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(400, "File is larger than 15 MB.")
    settings = get_settings()
    uploads = settings.data_path / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    upload_id = new_id()
    path = uploads / f"{upload_id}-{safe}"
    path.write_bytes(data)
    kind, excerpt = _describe_upload(path, file.content_type or "", safe)
    with session_scope() as db:
        row = Upload(
            id=upload_id,
            filename=safe,
            mime=file.content_type or "application/octet-stream",
            path=str(path),
            text_excerpt=excerpt,
            kind=kind,
        )
        db.add(row)
        db.flush()
        return {
            "id": row.id,
            "filename": row.filename,
            "mime": row.mime,
            "kind": row.kind,
            "excerpt": excerpt[:500],
        }


@router.get("/uploads/{upload_id}/raw")
def upload_raw(upload_id: str) -> FileResponse:
    with session_scope() as db:
        row = db.get(Upload, upload_id)
        if row is None:
            raise HTTPException(404, "Upload not found.")
        path = Path(row.path)
        media = row.mime
        name = row.filename
    if not path.exists():
        raise HTTPException(404, "Upload file is missing from disk.")
    return FileResponse(path, media_type=media, filename=name)


@router.get("/voice/capabilities")
def voice_capabilities() -> dict[str, Any]:
    with session_scope() as db:
        row = _settings(db)
        return capabilities(row.voice_provider, row.voice_id)


@router.post("/voice/transcribe")
async def voice_transcribe(file: UploadFile = File(...)) -> dict[str, str]:
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty audio.")
    try:
        text = await transcribe(data, file.filename or "speech.webm")
    except NotConfigured as exc:
        return JSONResponse({"fallback": "browser", "detail": str(exc)}, status_code=409)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, str(exc)) from exc
    return {"text": text}


@router.post("/voice/speak")
async def voice_speak(body: SpeakIn) -> StreamingResponse:
    with session_scope() as db:
        row = _settings(db)
        provider = row.voice_provider
        voice_id = row.voice_id
    try:
        content_type, iterator = await stream_tts(body.text, provider, voice_id)
    except NotConfigured as exc:
        return JSONResponse({"fallback": "browser", "detail": str(exc), "text": body.text}, status_code=409)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, str(exc)) from exc
    headers = {"Cache-Control": "no-store"}
    if content_type == "application/octet-stream":
        headers["X-Audio-Format"] = "pcm"
        headers["X-Sample-Rate"] = "24000"
    return StreamingResponse(iterator, media_type=content_type, headers=headers)


@router.post("/approvals/{approval_id}")
def decide_approval(approval_id: str, body: DecisionIn, request: Request) -> dict[str, bool]:
    if not request.app.state.approvals.resolve(approval_id, body.approved):
        raise HTTPException(404, "That approval is no longer waiting.")
    return {"ok": True, "approved": body.approved}


async def _websocket(websocket: WebSocket) -> None:
    live = websocket.scope["app"]
    await websocket.accept()
    live.state.hub.add(websocket)
    try:
        while True:
            try:
                payload = await websocket.receive_json()
            except WebSocketDisconnect:
                break
            except json.JSONDecodeError:
                await live.state.hub.send(websocket, {"type": "error", "detail": "Invalid JSON."})
                continue
            kind = payload.get("type")
            if kind == "ping":
                await live.state.hub.send(websocket, {"type": "pong"})
            elif kind == "approval_decision":
                live.state.approvals.resolve(str(payload.get("approval_id")), bool(payload.get("approved")))
            elif kind == "chat":
                asyncio.create_task(_safe_chat(live, websocket, payload))
            elif kind == "computer_stop":
                live.state.computer_stop.set()
            elif kind == "computer_task":
                if getattr(live.state, "computer_running", False):
                    await live.state.hub.send(websocket, {"type": "error", "detail": "A screen task is already running. Press Stop first."})
                else:
                    asyncio.create_task(_safe_computer(live, websocket, payload))
            else:
                await live.state.hub.send(websocket, {"type": "error", "detail": f"Unknown event '{kind}'."})
    finally:
        live.state.hub.discard(websocket)


async def _safe_computer(app: FastAPI, websocket: WebSocket, payload: dict[str, Any]) -> None:
    import threading

    from alex.computer_use.desktop import arm_emergency_stop
    from alex.computer_use.loop import run_computer_task
    from alex.llm.providers import get_router

    async def on_event(event: dict[str, Any]) -> None:
        try:
            await app.state.hub.send(websocket, event)
        except Exception:
            log.debug("socket send failed", exc_info=True)
        if event.get("type") == "computer_action":
            with session_scope() as db:
                db.add(
                    ActionLog(
                        tool_name="computer_use",
                        arguments_json=json.dumps({"action": event.get("action"), "reason": event.get("reason")})[:4000],
                        status="executed" if event.get("ok") else "failed",
                        result=str(event.get("summary") or "")[:4000],
                    )
                )

    async def approval(request: ActionRequest) -> bool:
        approval_id = new_id()
        future = app.state.approvals.create(approval_id)
        await on_event(
            {
                "type": "approval_required",
                "approval_id": approval_id,
                "tool": request.tool,
                "summary": request.summary,
                "arguments": request.arguments,
                "risk": request.risk,
            }
        )
        try:
            return bool(await asyncio.wait_for(future, timeout=300))
        except asyncio.TimeoutError:
            return False

    app.state.computer_stop = threading.Event()
    app.state.computer_running = True
    hotkey = arm_emergency_stop(app.state.computer_stop)
    await on_event({"type": "computer_status", "hotkey": hotkey, "running": True})
    try:
        with session_scope() as db:
            row = _settings(db)
            enabled = bool(row.computer_use_enabled)
            steps = int(row.computer_use_max_steps or 12)
            provider_name = row.provider
            model = row.model
        from alex.config import DEFAULT_MODELS

        model = (model or "").strip() or DEFAULT_MODELS.get(provider_name, "")
        await run_computer_task(
            goal=str(payload.get("goal") or "").strip(),
            on_event=on_event,
            approval=approval,
            stop_event=app.state.computer_stop,
            enabled=enabled,
            max_steps=steps,
            provider_name=provider_name,
            model=model,
            provider=get_router().get(provider_name),
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("computer task failed")
        await on_event({"type": "error", "detail": str(exc)})
    finally:
        app.state.computer_running = False
        await on_event({"type": "computer_status", "running": False, "hotkey": "Ctrl+Alt+Esc"})


async def _safe_chat(app: FastAPI, websocket: WebSocket, payload: dict[str, Any]) -> None:
    async def on_event(event: dict[str, Any]) -> None:
        try:
            await app.state.hub.send(websocket, event)
        except Exception:
            log.debug("socket send failed", exc_info=True)

    async def approval(request: ActionRequest) -> bool:
        approval_id = new_id()
        future = app.state.approvals.create(approval_id)
        await on_event(
            {
                "type": "approval_required",
                "approval_id": approval_id,
                "tool": request.tool,
                "summary": request.summary,
                "arguments": request.arguments,
                "risk": request.risk,
            }
        )
        try:
            return bool(await asyncio.wait_for(future, timeout=300))
        except asyncio.TimeoutError:
            return False

    try:
        await run_turn(
            content=str(payload.get("content") or ""),
            conversation_id=payload.get("conversation_id"),
            project_id=payload.get("project_id"),
            attachment_ids=list(payload.get("attachment_ids") or []),
            on_event=on_event,
            approval=approval,
            registry=app.state.registry,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("chat turn failed")
        await on_event({"type": "error", "detail": str(exc), "conversation_id": payload.get("conversation_id")})


def _settings(db: Session) -> AppSetting:
    row = db.get(AppSetting, 1)
    if row is None:
        raise HTTPException(500, "Settings are not initialized.")
    return row


def _settings_payload(db: Session) -> dict[str, Any]:
    from alex.config import DEFAULT_MODELS
    from alex.llm.providers import get_router

    row = _settings(db)
    provider = get_router().get(row.provider)
    model = row.model or DEFAULT_MODELS.get(row.provider, "")
    return {
        "assistant_name": row.assistant_name,
        "persona": row.persona,
        "provider": row.provider,
        "model": row.model,
        "effective_model": model,
        "voice_provider": row.voice_provider,
        "voice_id": row.voice_id,
        "auto_speak": row.auto_speak,
        "voice_wake": bool(getattr(row, "voice_wake", False)),
        "wake_phrase": getattr(row, "wake_phrase", None) or "alex",
        "computer_use_enabled": bool(getattr(row, "computer_use_enabled", False)),
        "computer_use_max_steps": int(getattr(row, "computer_use_max_steps", None) or 12),
        "search_provider": row.search_provider,
        "github_repo": get_settings().alex_github_repo,
        "update_manifest": get_settings().alex_update_manifest,
        "update_token_set": bool(get_settings().alex_update_token.strip()),
        "safe_folders": json.loads(row.safe_folders or "[]"),
        "command_allowlist": allowlist(row),
        "provider_configured": provider.is_configured(),
        "provider_detail": provider.status_detail(),
        "providers": [
            {
                "id": item.id,
                "label": item.label,
                "configured": item.is_configured(),
                "detail": item.status_detail(),
                "models": MODEL_CHOICES.get(item.id, []),
            }
            for item in get_router().providers.values()
        ],
        "keys": _key_status(),
        "key_help": KEY_HELP,
        "shell": shell_name(),
        "voice": capabilities(row.voice_provider, row.voice_id),
    }


def _key_status() -> dict[str, bool]:
    settings = get_settings()
    return {
        "openai": bool(settings.openai_api_key.strip()),
        "anthropic": bool(settings.anthropic_api_key.strip()),
        "xai": bool(settings.xai_api_key.strip()),
        "elevenlabs": bool(settings.elevenlabs_api_key.strip()),
        "elevenlabs_voice": bool(settings.elevenlabs_voice_id.strip()),
        "tavily": bool(settings.tavily_api_key.strip()),
        "brave": bool(settings.brave_search_api_key.strip()),
    }


def _normalize_folders(items: list[str]) -> list[str]:
    cleaned: list[str] = []
    for item in items:
        text = expand_user_path(str(item))
        if not text:
            continue
        path = Path(text)
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise HTTPException(400, f"Could not use folder {text}: {exc}") from exc
        resolved = str(path.resolve())
        if resolved not in cleaned:
            cleaned.append(resolved)
    return cleaned


def _normalize_allowlist(items: list[str]) -> list[str]:
    cleaned: list[str] = []
    for item in items:
        token = str(item).strip()
        if not token:
            continue
        if any(ch.isspace() for ch in token):
            raise HTTPException(400, f"Allowlist entries are the first token only, not a full command: {token}")
        if token not in cleaned:
            cleaned.append(token[:80])
        if len(cleaned) > 40:
            break
    return cleaned


def _conversation_dict(row: Conversation) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "project_id": row.project_id,
        "project_name": row.project.name if row.project else None,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _message_dict(row: Message) -> dict[str, Any]:
    meta = _loads(row.metadata_json)
    return {
        "id": row.id,
        "role": row.role,
        "content": row.content,
        "tool_name": row.tool_name,
        "tool_call_id": row.tool_call_id,
        "ok": meta.get("ok"),
        "sources": meta.get("sources") or [],
        "tool_calls": meta.get("tool_calls") or [],
        "created_at": _iso(row.created_at),
    }


def _project_dict(row: Project, db: Session) -> dict[str, Any]:
    count = db.query(Conversation).filter(Conversation.project_id == row.id).count()
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "folder": row.folder,
        "conversation_count": count,
        "created_at": _iso(row.created_at),
    }


def _reminder_dict(row: Reminder) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "notes": row.notes,
        "due_at": _iso(row.due_at),
        "status": row.status,
        "fired_at": _iso(row.fired_at),
        "created_at": _iso(row.created_at),
    }


def _automation_dict(row: Automation) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "prompt": row.prompt,
        "interval_seconds": row.interval_seconds,
        "enabled": row.enabled,
        "last_run_at": _iso(row.last_run_at),
        "next_run_at": _iso(row.next_run_at),
        "last_result": row.last_result,
        "conversation_id": row.conversation_id,
        "created_at": _iso(row.created_at),
    }


def _notification_dict(row: Notification) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "body": row.body,
        "kind": row.kind,
        "read": row.read,
        "created_at": _iso(row.created_at),
    }


def _parse_due(due_at: str | None, due_in_seconds: int | None) -> datetime:
    if due_in_seconds is not None:
        return datetime.now(timezone.utc) + timedelta(seconds=max(1, int(due_in_seconds)))
    if due_at:
        text = due_at.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise HTTPException(400, "due_at must be an ISO-8601 timestamp.") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    raise HTTPException(400, "Provide due_at or due_in_seconds.")


def _describe_upload(path: Path, mime: str, filename: str) -> tuple[str, str]:
    suffix = Path(filename).suffix.lower()
    if mime.startswith("image/") or suffix in IMAGE_SUFFIXES:
        return "image", ""
    if suffix == ".docx" or mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        try:
            from docx import Document

            document = Document(str(path))
            text = "\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text)
        except Exception as exc:  # noqa: BLE001
            text = f"(Could not read DOCX: {exc})"
        return "docx", text[:20000]
    if suffix == ".pdf" or mime == "application/pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            text = "\n".join((page.extract_text() or "") for page in reader.pages[:30])
        except Exception as exc:  # noqa: BLE001
            text = f"(Could not read PDF: {exc})"
        return "pdf", text[:20000]
    if suffix in TEXT_SUFFIXES or mime.startswith("text/") or mime in {"application/json", "application/xml"}:
        return "text", path.read_text(encoding="utf-8", errors="replace")[:20000]
    return "other", ""


def _safe_name(name: str) -> str:
    base = Path(name).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base).strip("._") or "upload"
    return cleaned[:120]


def _loads(raw: str | None) -> dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {"value": data}


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()
