"""Store, edit, and retrieve memories about the owner."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from alex.memory.embeddings import embedding_payload, score_memory
from alex.models import Memory, utcnow

# Soft facts. Explicit "remember that ..." is handled by the remember tool
# and by extract_explicit, which the chat engine runs if the model skips the tool.
_SOFT = [
    ("preference", re.compile(r"\bi (?:prefer|like|love|hate|enjoy)\s+([^.\n!]{3,160})", re.I)),
    ("fact", re.compile(r"\bmy name is\s+([^.!\n]{2,80})", re.I)),
    ("preference", re.compile(r"\bcall me\s+([^.\n!]{2,60})", re.I)),
    ("fact", re.compile(r"\bi work (?:at|for|on)\s+([^.\n!]{3,120})", re.I)),
    ("fact", re.compile(r"\bi live in\s+([^.\n!]{3,80})", re.I)),
    ("preference", re.compile(r"\bmy favorite\s+([^.\n!]{3,120})", re.I)),
    ("preference", re.compile(r"\bi usually\s+([^.\n!]{3,120})", re.I)),
]
_EXPLICIT = re.compile(r"\bremember that\s+([^.\n!]{3,400})", re.I)


def list_memories(db: Session, query: str = "") -> list[Memory]:
    rows = list(db.scalars(select(Memory).order_by(Memory.updated_at.desc())).all())
    if not query.strip():
        return rows
    ranked = sorted(rows, key=lambda row: score_memory(query, row.content, row.embedding_json), reverse=True)
    return [row for row in ranked if score_memory(query, row.content, row.embedding_json) > 0.05]


def retrieve(db: Session, query: str, k: int = 5) -> list[Memory]:
    rows = list(db.scalars(select(Memory)).all())
    if not rows or not query.strip():
        return []
    ranked = sorted(rows, key=lambda row: score_memory(query, row.content, row.embedding_json), reverse=True)
    top = [row for row in ranked if score_memory(query, row.content, row.embedding_json) >= 0.18]
    return top[:k]


def remember(db: Session, content: str, kind: str = "fact", source: str = "user") -> Memory:
    content = " ".join(content.strip().split())
    if not content:
        raise ValueError("Memory text is empty.")
    existing = _near_duplicate(db, content)
    if existing is not None:
        existing.content = content
        existing.kind = kind or existing.kind
        existing.source = source or existing.source
        existing.embedding_json = embedding_payload(content)
        existing.updated_at = utcnow()
        db.add(existing)
        db.flush()
        return existing
    row = Memory(
        content=content,
        kind=kind or "fact",
        source=source or "user",
        embedding_json=embedding_payload(content),
    )
    db.add(row)
    db.flush()
    return row


def update_memory(db: Session, memory_id: str, content: str, kind: str | None = None) -> Memory | None:
    row = db.get(Memory, memory_id)
    if row is None:
        return None
    row.content = " ".join(content.strip().split())
    if kind:
        row.kind = kind
    row.embedding_json = embedding_payload(row.content)
    row.updated_at = utcnow()
    db.add(row)
    db.flush()
    return row


def delete_memory(db: Session, memory_id: str) -> bool:
    row = db.get(Memory, memory_id)
    if row is None:
        return False
    db.delete(row)
    db.flush()
    return True


def forget_matching(db: Session, query: str) -> Memory | None:
    rows = list(db.scalars(select(Memory)).all())
    if not rows:
        return None
    best = max(rows, key=lambda row: score_memory(query, row.content, row.embedding_json))
    if score_memory(query, best.content, best.embedding_json) < 0.28:
        return None
    db.delete(best)
    db.flush()
    return best


def extract_explicit(text: str) -> list[str]:
    return [" ".join(match.group(1).split()) for match in _EXPLICIT.finditer(text or "")]


def extract_soft(text: str) -> list[tuple[str, str]]:
    if re.match(r"\s*remember that\b", text or "", re.I):
        return []
    found: list[tuple[str, str]] = []
    for kind, pattern in _SOFT:
        for match in pattern.finditer(text or ""):
            fact = " ".join(match.group(1).split())
            if len(fact) < 3:
                continue
            if kind == "fact" and fact.lower().startswith("name is"):
                continue
            found.append((kind, fact if kind != "preference" else _preference_sentence(match)))
    return found


def _preference_sentence(match: re.Match[str]) -> str:
    raw = match.group(0).strip().rstrip(".")
    raw = raw[0].upper() + raw[1:]
    return raw


def store_extracted(db: Session, text: str, source: str = "extracted") -> list[Memory]:
    saved: list[Memory] = []
    for fact in extract_explicit(text):
        saved.append(remember(db, fact, kind="explicit", source=source))
    for kind, fact in extract_soft(text):
        saved.append(remember(db, fact, kind=kind, source=source))
    return saved


def _near_duplicate(db: Session, content: str) -> Memory | None:
    rows = list(db.scalars(select(Memory)).all())
    best: Memory | None = None
    best_score = 0.0
    for row in rows:
        score = score_memory(content, row.content, row.embedding_json)
        if score > best_score:
            best = row
            best_score = score
    if best is not None and best_score >= 0.92:
        return best
    normalized = content.lower().strip()
    for row in rows:
        if row.content.lower().strip() == normalized:
            return row
    return None


def as_dict(row: Memory) -> dict:
    return {
        "id": row.id,
        "content": row.content,
        "kind": row.kind,
        "source": row.source,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()
