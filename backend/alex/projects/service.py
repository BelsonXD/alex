"""Project folders live under the owner's ALEX directory so Explorer can open them."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from alex.config import DEFAULT_PERSONA, get_settings
from alex.models import AppSetting, Project, new_id, utcnow
from alex.tools.computer import default_alex_root


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug or "project"


def seed_defaults(db: Session) -> AppSetting:
    settings = get_settings()
    data = settings.data_path
    sandbox = data / "sandbox"
    uploads = data / "uploads"
    sandbox.mkdir(parents=True, exist_ok=True)
    uploads.mkdir(parents=True, exist_ok=True)
    readme = sandbox / "README.txt"
    if not readme.exists():
        readme.write_text(
            "This is ALEX's sandbox. File tools may list, read, and — after you approve — change files in here.\n",
            encoding="utf-8",
        )
    folders = [str(sandbox.resolve())]
    try:
        root = default_alex_root()
        root.mkdir(parents=True, exist_ok=True)
        (root / "Projects").mkdir(parents=True, exist_ok=True)
        marker = root / "README.txt"
        if not marker.exists():
            marker.write_text(
                "ALEX keeps project workspaces in the Projects folder next to this file.\n"
                "Add more safe folders from Settings if you want ALEX to work elsewhere.\n",
                encoding="utf-8",
            )
        folders.append(str(root.resolve()))
    except OSError:
        pass

    row = db.get(AppSetting, 1)
    if row is None:
        row = AppSetting(
            id=1,
            assistant_name="ALEX",
            persona=DEFAULT_PERSONA,
            provider=settings.alex_provider or "offline",
            model=settings.alex_model or "",
            voice_provider="browser",
            voice_id="nova",
            auto_speak=False,
            search_provider="auto",
            safe_folders=json.dumps(folders),
            command_allowlist="[]",
        )
        db.add(row)
        db.flush()
    return row


def safe_folder_list(row: AppSetting) -> list[Path]:
    try:
        raw = json.loads(row.safe_folders or "[]")
    except json.JSONDecodeError:
        raw = []
    folders: list[Path] = []
    for item in raw:
        path = Path(str(item)).expanduser()
        if path.exists() and path.is_dir():
            folders.append(path.resolve())
        elif not path.exists():
            try:
                path.mkdir(parents=True, exist_ok=True)
                folders.append(path.resolve())
            except OSError:
                continue
    return folders


def allowlist(row: AppSetting) -> list[str]:
    try:
        raw = json.loads(row.command_allowlist or "[]")
    except json.JSONDecodeError:
        return []
    return [str(item) for item in raw if str(item).strip()]


def allocate_project_dir(name: str, project_id: str) -> Path:
    root = default_alex_root() / "Projects"
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        root = get_settings().data_path / "workspaces"
        root.mkdir(parents=True, exist_ok=True)
    folder = root / f"{slugify(name)}-{project_id[:8]}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder.resolve()


def create_project(db: Session, name: str, description: str = "") -> Project:
    name = name.strip()
    if not name:
        raise ValueError("Project name is required.")
    project_id = new_id()
    folder = allocate_project_dir(name, project_id)
    row = Project(
        id=project_id,
        name=name,
        description=description.strip(),
        folder=str(folder),
        created_at=utcnow(),
    )
    db.add(row)
    db.flush()
    return row


def delete_project(db: Session, project: Project, delete_files: bool) -> None:
    folder = Path(project.folder) if project.folder else None
    if delete_files and folder and folder.exists():
        settings_row = db.get(AppSetting, 1)
        roots = safe_folder_list(settings_row) if settings_row else []
        from alex.tools.computer import is_within

        if any(is_within(folder, root) for root in roots):
            shutil.rmtree(folder)
    db.delete(project)
    db.flush()


def list_folder(folder: Path) -> list[dict]:
    if not folder.exists():
        return []
    items = []
    for path in sorted(folder.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        stat = path.stat()
        items.append(
            {
                "name": path.name,
                "path": str(path),
                "is_dir": path.is_dir(),
                "size": 0 if path.is_dir() else stat.st_size,
            }
        )
    return items
