"""Fires due reminders and runs scheduled prompts. Sensitive tools are denied."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI

from alex.chat.engine import run_turn
from alex.database import session_scope
from alex.models import Automation, Notification, Reminder, new_id, utcnow
from alex.tools.registry import ActionRequest

log = logging.getLogger("alex.scheduler")


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def scheduler_loop(stop: asyncio.Event, app: FastAPI) -> None:
    while not stop.is_set():
        try:
            notes = await process_due(app)
            for note in notes:
                await app.state.hub.broadcast({"type": "notification", "notification": note})
        except Exception:
            log.exception("scheduler pass failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=5)
        except asyncio.TimeoutError:
            continue


async def process_due(app: FastAPI) -> list[dict[str, Any]]:
    notes = _fire_reminders()
    automation_ids = _claim_automations()
    for automation_id in automation_ids:
        note = await _run_automation(app, automation_id)
        if note:
            notes.append(note)
    return notes


def _fire_reminders() -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    notes: list[dict[str, Any]] = []
    with session_scope() as db:
        rows = db.query(Reminder).filter(Reminder.status == "pending").all()
        for row in rows:
            if _aware(row.due_at) > now:
                continue
            row.status = "fired"
            row.fired_at = utcnow()
            note = Notification(
                id=new_id(),
                title=row.title,
                body=row.notes or "Reminder",
                kind="reminder",
            )
            db.add(note)
            db.flush()
            notes.append(_note_dict(note))
            from alex.notify import notify

            notify(row.title, row.notes or "Reminder")
    return notes


def _claim_automations() -> list[str]:
    now = datetime.now(timezone.utc)
    claimed: list[str] = []
    with session_scope() as db:
        rows = db.query(Automation).filter(Automation.enabled.is_(True)).all()
        for row in rows:
            due = row.next_run_at or row.created_at
            if due is None or _aware(due) > now:
                continue
            row.last_run_at = utcnow()
            row.next_run_at = utcnow() + timedelta(seconds=max(30, int(row.interval_seconds or 3600)))
            claimed.append(row.id)
    return claimed


async def _run_automation(app: FastAPI, automation_id: str) -> dict[str, Any] | None:
    with session_scope() as db:
        row = db.get(Automation, automation_id)
        if row is None:
            return None
        prompt = row.prompt
        name = row.name
        conversation_id = row.conversation_id
    chunks: list[str] = []

    async def on_event(event: dict[str, Any]) -> None:
        if event.get("type") == "token":
            chunks.append(event.get("text") or "")
        if event.get("type") == "conversation" and event.get("conversation_id"):
            with session_scope() as db:
                current = db.get(Automation, automation_id)
                if current and not current.conversation_id:
                    current.conversation_id = event["conversation_id"]

    async def deny(_request: ActionRequest) -> bool:
        return False

    try:
        await run_turn(
            content=prompt,
            conversation_id=conversation_id,
            project_id=None,
            attachment_ids=[],
            on_event=on_event,
            approval=deny,
            registry=app.state.registry,
            source="automation",
        )
        result = "".join(chunks).strip() or "(no text)"
    except Exception as exc:  # noqa: BLE001
        result = f"Automation failed: {exc}"
        log.exception("automation %s failed", automation_id)

    with session_scope() as db:
        row = db.get(Automation, automation_id)
        if row is not None:
            row.last_result = result[:8000]
        note = Notification(
            id=new_id(),
            title=f"Automation · {name}",
            body=result[:2000],
            kind="automation",
        )
        db.add(note)
        db.flush()
        return _note_dict(note)


def _note_dict(note: Notification) -> dict[str, Any]:
    created = note.created_at
    if created is not None and created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return {
        "id": note.id,
        "title": note.title,
        "body": note.body,
        "kind": note.kind,
        "read": note.read,
        "created_at": created.isoformat() if created else None,
    }
