"""Built-in tools: memory, search, files, PowerShell, reminders, projects."""

from __future__ import annotations

import ast
import json
import math
import operator
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import psutil
from sqlalchemy.orm import Session

from alex.config import KEY_HELP
from alex.memory import service as memory
from alex.models import ActionLog, Project, Reminder, new_id, utcnow
from alex.projects import service as projects
from alex.tools.computer import (
    build_open_app_argv,
    build_open_url_argv,
    build_shell_argv,
    format_process,
    resolve_inside,
    run_process,
    shell_name,
    special_folder,
)
from alex.tools.registry import Registry, ToolResult

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}
_FUNCS = {
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "log": math.log,
    "abs": abs,
    "round": round,
}


@dataclass
class ToolContext:
    db_factory: Any
    safe_folders: list[Path]
    allowlist: list[str] = field(default_factory=list)
    system_name: str = platform.system()
    search_provider: str = "auto"
    tavily_api_key: str = ""
    brave_api_key: str = ""
    project_id: str | None = None
    workspace: Path | None = None
    sandbox: Path | None = None


def register_builtin(registry: Registry) -> None:
    specs = [
        ("remember", "Store a durable fact or preference about Sahib.", _obj({"content": _str("The fact to remember."), "kind": _str("fact, preference, or explicit.")}, ["content"]), False, tool_remember),
        ("forget", "Delete the memory that best matches a description.", _obj({"query": _str("What to forget.")}, ["query"]), False, tool_forget),
        ("recall", "Search long-term memories.", _obj({"query": _str("What to look up.")}, ["query"]), False, tool_recall),
        ("web_search", "Search the web and return titles, URLs, and snippets. Use this for current information.", _obj({"query": _str("Search query.")}, ["query"]), False, tool_search),
        ("list_files", "List files inside a safe folder. Use directory 'sandbox', 'desktop', 'documents', 'downloads', or a path.", _obj({"directory": _str("Folder alias or path. Defaults to the sandbox."), "limit": {"type": "integer"}}, []), False, tool_list_files),
        ("read_file", "Read a text file inside a safe folder.", _obj({"path": _str("File path or sandbox-relative path.")}, ["path"]), False, tool_read_file),
        ("write_file", "Create or overwrite a text file inside a safe folder. Use this to save code into the active project. Requires Sahib's approval.", _obj({"path": _str("Destination path."), "content": _str("Full file contents.")}, ["path", "content"]), True, tool_write_file),
        ("move_file", "Move or rename a file inside the safe folders. Requires approval.", _obj({"source": _str("Current path."), "destination": _str("New path.")}, ["source", "destination"]), True, tool_move_file),
        ("delete_file", "Delete a file inside a safe folder. Requires approval.", _obj({"path": _str("File to delete.")}, ["path"]), True, tool_delete_file),
        ("organize_files", "Move files matching a glob into a subfolder. Requires approval.", _obj({"directory": _str("Folder to organize."), "pattern": _str("Glob such as *.png"), "destination": _str("Subfolder name.")}, ["directory", "pattern", "destination"]), True, tool_organize),
        ("run_command", "Run a command on this computer. On Windows the command is PowerShell. On macOS and Linux it is bash. Requires approval unless the first token is on the allowlist.", _obj({"command": _str("The exact command."), "cwd": _str("Optional working directory inside a safe folder.")}, ["command"]), True, tool_run_command),
        ("open_app", "Open an application on this computer. On Windows this uses Start-Process and the Start menu. Requires approval.", _obj({"name": _str("App name, for example notepad, calc, or the Start menu name.")}, ["name"]), True, tool_open_app),
        ("open_url", "Open an http(s) URL in the default browser. Requires approval.", _obj({"url": _str("Absolute http or https URL.")}, ["url"]), True, tool_open_url),
        ("create_reminder", "Save a reminder. Pass due_in_seconds or due_at (ISO-8601).", _obj({"title": _str("What to remember to do."), "due_in_seconds": {"type": "integer"}, "due_at": _str("ISO timestamp."), "notes": _str("Optional notes.")}, ["title"]), False, tool_create_reminder),
        ("list_reminders", "List reminders.", _obj({}, []), False, tool_list_reminders),
        ("get_time", "Current local time and UTC time.", _obj({}, []), False, tool_time),
        ("get_system_info", "CPU, memory, platform, and safe folders for the machine running ALEX.", _obj({}, []), False, tool_system),
        ("calculate", "Evaluate a math expression locally. Supports + - * / ** sqrt sin cos log abs round.", _obj({"expression": _str("Math expression.")}, ["expression"]), False, tool_calculate),
        ("list_projects", "List ALEX projects and their folders.", _obj({}, []), False, tool_list_projects),
        ("create_project", "Create a project and its folder on disk.", _obj({"name": _str("Project name."), "description": _str("What it is for.")}, ["name"]), False, tool_create_project),
    ]
    for name, description, parameters, needs, handler in specs:
        registry.tool(
            name=name,
            description=description,
            parameters=parameters,
            needs_approval=needs,
            handler=handler,
        )


def _str(description: str) -> dict[str, str]:
    return {"type": "string", "description": description}


def _obj(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required}


def command_is_allowlisted(command: str, allowlist: list[str]) -> bool:
    token = (command or "").strip().split(" ", 1)[0].lower()
    if not token:
        return False
    return token in {item.strip().lower() for item in allowlist if item.strip()}


async def tool_remember(args: dict, ctx: ToolContext) -> ToolResult:
    content = str(args.get("content") or "").strip()
    kind = str(args.get("kind") or "fact").strip() or "fact"
    with ctx.db_factory() as db:
        row = memory.remember(db, content, kind=kind, source="tool")
        text = row.content
    return ToolResult(True, f"Stored memory: {text}")


async def tool_forget(args: dict, ctx: ToolContext) -> ToolResult:
    query = str(args.get("query") or "").strip()
    with ctx.db_factory() as db:
        row = memory.forget_matching(db, query)
        if row is None:
            return ToolResult(False, f"No memory matched '{query}'.")
        return ToolResult(True, f"Forgot: {row.content}")


async def tool_recall(args: dict, ctx: ToolContext) -> ToolResult:
    query = str(args.get("query") or "").strip()
    with ctx.db_factory() as db:
        rows = memory.retrieve(db, query, k=8) if query else memory.list_memories(db)[:8]
        if not rows:
            return ToolResult(True, "No memories stored yet.")
        lines = [f"- ({row.kind}) {row.content}" for row in rows]
    return ToolResult(True, "Memories:\n" + "\n".join(lines))


async def tool_search(args: dict, ctx: ToolContext) -> ToolResult:
    query = str(args.get("query") or "").strip()
    if not query:
        return ToolResult(False, "Search query is empty.")
    provider = _pick_search(ctx)
    if provider is None:
        return ToolResult(
            False,
            "Web search is not configured. Add TAVILY_API_KEY "
            f"({KEY_HELP['tavily']}) or BRAVE_SEARCH_API_KEY ({KEY_HELP['brave']}) to the .env file.",
        )
    if provider == "tavily":
        sources = await _tavily(query, ctx.tavily_api_key)
    else:
        sources = await _brave(query, ctx.brave_api_key)
    if not sources:
        return ToolResult(True, "Search returned no results.", [])
    lines = [f"- {item['title']} — {item['url']}\n  {item['snippet']}" for item in sources]
    return ToolResult(True, "Search results:\n" + "\n".join(lines), sources)


def _pick_search(ctx: ToolContext) -> str | None:
    choice = (ctx.search_provider or "auto").lower()
    if choice == "tavily" and ctx.tavily_api_key:
        return "tavily"
    if choice == "brave" and ctx.brave_api_key:
        return "brave"
    if choice in {"auto", ""}:
        if ctx.tavily_api_key:
            return "tavily"
        if ctx.brave_api_key:
            return "brave"
    if choice == "tavily" and not ctx.tavily_api_key and ctx.brave_api_key:
        return "brave"
    if choice == "brave" and not ctx.brave_api_key and ctx.tavily_api_key:
        return "tavily"
    return None


async def _tavily(query: str, api_key: str) -> list[dict[str, str]]:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://api.tavily.com/search",
            json={"api_key": api_key, "query": query, "max_results": 5, "include_answer": False},
        )
        response.raise_for_status()
        payload = response.json()
    sources = []
    for item in payload.get("results") or []:
        sources.append(
            {
                "title": str(item.get("title") or item.get("url") or "Result"),
                "url": str(item.get("url") or ""),
                "snippet": str(item.get("content") or "")[:500],
            }
        )
    return sources


async def _brave(query: str, api_key: str) -> list[dict[str, str]]:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": 5},
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
    sources = []
    for item in (payload.get("web") or {}).get("results") or []:
        sources.append(
            {
                "title": str(item.get("title") or "Result"),
                "url": str(item.get("url") or ""),
                "snippet": str(item.get("description") or "")[:500],
            }
        )
    return sources


def _directory(raw: str, ctx: ToolContext) -> Path:
    text = (raw or "").strip()
    if not text or text.lower() in {"sandbox", "workspace", "project"}:
        if text.lower() in {"workspace", "project"} and ctx.workspace:
            return ctx.workspace
        if ctx.sandbox:
            return ctx.sandbox
        if ctx.safe_folders:
            return ctx.safe_folders[0]
        raise PermissionError("No safe folders are configured.")
    alias = special_folder(text, ctx.sandbox or (ctx.safe_folders[0] if ctx.safe_folders else Path(".")))
    if alias is not None and text.lower() in {"sandbox", "desktop", "documents", "downloads", "home"}:
        return resolve_inside(str(alias), ctx.safe_folders)
    return resolve_inside(text, ctx.safe_folders)


async def tool_list_files(args: dict, ctx: ToolContext) -> ToolResult:
    limit = int(args.get("limit") or 100)
    folder = _directory(str(args.get("directory") or ""), ctx)
    if not folder.exists():
        return ToolResult(False, f"Folder does not exist: {folder}")
    lines = [str(folder)]
    count = 0
    for path in sorted(folder.iterdir(), key=lambda item: item.name.lower()):
        kind = "dir" if path.is_dir() else f"{path.stat().st_size} B"
        lines.append(f"  {path.name}  ({kind})")
        count += 1
        if count >= limit:
            lines.append("  …")
            break
    if count == 0:
        lines.append("  (empty)")
    return ToolResult(True, "\n".join(lines))


async def tool_read_file(args: dict, ctx: ToolContext) -> ToolResult:
    path = resolve_inside(str(args.get("path") or ""), ctx.safe_folders)
    if not path.is_file():
        return ToolResult(False, f"Not a file: {path}")
    data = path.read_bytes()[:200_000]
    if b"\x00" in data[:1024]:
        return ToolResult(False, f"{path.name} looks like a binary file. I did not dump it.")
    text = data.decode("utf-8", errors="replace")
    if len(text) > 16000:
        text = text[:16000] + "\n…truncated…"
    return ToolResult(True, f"{path}\n\n{text}")


async def tool_write_file(args: dict, ctx: ToolContext) -> ToolResult:
    raw = str(args.get("path") or "").strip()
    content = args.get("content")
    if content is None:
        return ToolResult(False, "content is required.")
    path = _target_path(raw, ctx)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(content), encoding="utf-8", newline="\n")
    return ToolResult(True, f"Wrote {path} ({len(str(content))} characters).")


def _target_path(raw: str, ctx: ToolContext) -> Path:
    if not raw:
        raise ValueError("path is required.")
    expanded = Path(raw)
    if not expanded.is_absolute() and ctx.workspace is not None:
        return resolve_inside(str(ctx.workspace / raw), ctx.safe_folders)
    return resolve_inside(raw, ctx.safe_folders)


async def tool_move_file(args: dict, ctx: ToolContext) -> ToolResult:
    source = resolve_inside(str(args.get("source") or ""), ctx.safe_folders)
    dest = _target_path(str(args.get("destination") or ""), ctx)
    if not source.exists():
        return ToolResult(False, f"Source does not exist: {source}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(dest))
    return ToolResult(True, f"Moved {source} -> {dest}")


async def tool_delete_file(args: dict, ctx: ToolContext) -> ToolResult:
    path = resolve_inside(str(args.get("path") or ""), ctx.safe_folders)
    if path.is_dir():
        return ToolResult(False, "Refusing to delete a directory with delete_file. Move files out first.")
    if not path.exists():
        return ToolResult(False, f"File does not exist: {path}")
    path.unlink()
    return ToolResult(True, f"Deleted {path}")


async def tool_organize(args: dict, ctx: ToolContext) -> ToolResult:
    folder = _directory(str(args.get("directory") or ""), ctx)
    pattern = str(args.get("pattern") or "").strip()
    destination = str(args.get("destination") or "").strip()
    if not pattern or "**" in pattern or any(part in pattern for part in ("..", "/", "\\")):
        return ToolResult(False, "Pattern must be a filename glob such as *.txt, with no path separators.")
    if not destination or any(part in destination for part in ("..", "/", "\\", ":")):
        return ToolResult(False, "Destination must be a simple subfolder name.")
    target = resolve_inside(str(folder / destination), ctx.safe_folders)
    target.mkdir(parents=True, exist_ok=True)
    moved = []
    for path in folder.glob(pattern):
        if not path.is_file() or path.parent != folder:
            continue
        dest = target / path.name
        shutil.move(str(path), str(dest))
        moved.append(path.name)
    if not moved:
        return ToolResult(True, f"No files matched {pattern} in {folder}.")
    return ToolResult(True, f"Moved {len(moved)} file(s) into {target}: {', '.join(moved)}")


async def tool_run_command(args: dict, ctx: ToolContext) -> ToolResult:
    command = str(args.get("command") or "").strip()
    if not command:
        return ToolResult(False, "Command is empty.")
    if len(command) > 4000:
        return ToolResult(False, "Command is longer than 4000 characters.")
    cwd_raw = str(args.get("cwd") or "").strip()
    if cwd_raw:
        cwd = resolve_inside(cwd_raw, ctx.safe_folders)
    elif ctx.workspace:
        cwd = ctx.workspace
    elif ctx.safe_folders:
        cwd = ctx.safe_folders[0]
    else:
        return ToolResult(False, "No safe folder is available as a working directory.")
    if not cwd.exists():
        cwd.mkdir(parents=True, exist_ok=True)
    timeout = 30
    try:
        proc = run_process(build_shell_argv(command, ctx.system_name), cwd, timeout, ctx.system_name)
    except subprocess.TimeoutExpired:
        return ToolResult(False, f"Command timed out after {timeout} seconds and was stopped.")
    except FileNotFoundError as exc:
        return ToolResult(False, f"Could not start {shell_name(ctx.system_name)}: {exc}")
    ok, text = format_process(proc)
    header = f"{shell_name(ctx.system_name)} in {cwd}\n{command}\n\n"
    return ToolResult(ok, header + text)


async def tool_open_app(args: dict, ctx: ToolContext) -> ToolResult:
    name = str(args.get("name") or "").strip()
    if not name:
        return ToolResult(False, "Application name is empty.")
    try:
        proc = run_process(build_open_app_argv(name, ctx.system_name), None, 20, ctx.system_name)
    except FileNotFoundError as exc:
        return ToolResult(False, f"Could not launch an application opener: {exc}")
    ok, text = format_process(proc)
    return ToolResult(ok, text)


async def tool_open_url(args: dict, ctx: ToolContext) -> ToolResult:
    url = str(args.get("url") or "").strip()
    if not (url.startswith("https://") or url.startswith("http://")):
        return ToolResult(False, "URL must start with http:// or https://.")
    try:
        proc = run_process(build_open_url_argv(url, ctx.system_name), None, 20, ctx.system_name)
    except FileNotFoundError as exc:
        return ToolResult(False, f"Could not open a browser: {exc}")
    ok, text = format_process(proc)
    return ToolResult(ok, text or f"Opened {url}")


async def tool_create_reminder(args: dict, ctx: ToolContext) -> ToolResult:
    title = str(args.get("title") or "").strip()
    if not title:
        return ToolResult(False, "Reminder title is empty.")
    due = _due_from_args(args)
    notes = str(args.get("notes") or "")
    with ctx.db_factory() as db:
        row = Reminder(id=new_id(), title=title, notes=notes, due_at=due, status="pending")
        db.add(row)
        db.flush()
        when = row.due_at.isoformat()
    return ToolResult(True, f"Reminder set: {title} at {when}")


def _due_from_args(args: dict) -> datetime:
    if args.get("due_in_seconds") is not None:
        seconds = max(1, int(args["due_in_seconds"]))
        return datetime.now(timezone.utc) + timedelta(seconds=seconds)
    raw = str(args.get("due_at") or "").strip()
    if raw:
        text = raw.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return datetime.now(timezone.utc) + timedelta(hours=1)


async def tool_list_reminders(args: dict, ctx: ToolContext) -> ToolResult:
    del args
    with ctx.db_factory() as db:
        rows = db.query(Reminder).order_by(Reminder.due_at.asc()).all()
        if not rows:
            return ToolResult(True, "No reminders.")
        lines = [f"- [{row.status}] {row.title} due {row.due_at.isoformat()}" for row in rows]
    return ToolResult(True, "\n".join(lines))


async def tool_time(args: dict, ctx: ToolContext) -> ToolResult:
    del args, ctx
    now = datetime.now().astimezone()
    return ToolResult(True, f"Local: {now.isoformat()}\nUTC: {datetime.now(timezone.utc).isoformat()}")


async def tool_system(args: dict, ctx: ToolContext) -> ToolResult:
    del args
    vm = psutil.virtual_memory()
    text = "\n".join(
        [
            f"Platform: {platform.platform()}",
            f"Shell: {shell_name(ctx.system_name)}",
            f"CPU: {psutil.cpu_percent(interval=0.05):.0f}%",
            f"Memory: {vm.percent:.0f}% ({vm.used // (1024 * 1024)} MB used)",
            "Safe folders:",
            *[f"  {folder}" for folder in ctx.safe_folders],
        ]
    )
    return ToolResult(True, text)


async def tool_calculate(args: dict, ctx: ToolContext) -> ToolResult:
    del ctx
    expression = str(args.get("expression") or "").strip()
    try:
        value = _eval_math(expression)
    except Exception as exc:  # noqa: BLE001 — return the math error to the model
        return ToolResult(False, f"Could not calculate: {exc}")
    return ToolResult(True, f"{expression} = {value}")


def _eval_math(expression: str) -> float:
    tree = ast.parse(expression, mode="eval")

    def walk(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return float(_OPS[type(node.op)](walk(node.operand)))
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return float(_OPS[type(node.op)](walk(node.left), walk(node.right)))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
            fn = _FUNCS[node.func.id]
            return float(fn(*(walk(arg) for arg in node.args)))
        raise ValueError("Only numbers and basic math functions are allowed.")

    return walk(tree)


async def tool_list_projects(args: dict, ctx: ToolContext) -> ToolResult:
    del args
    with ctx.db_factory() as db:
        rows = db.query(Project).order_by(Project.created_at.desc()).all()
        if not rows:
            return ToolResult(True, "No projects yet.")
        lines = [f"- {row.name}: {row.folder}" for row in rows]
    return ToolResult(True, "\n".join(lines))


async def tool_create_project(args: dict, ctx: ToolContext) -> ToolResult:
    name = str(args.get("name") or "").strip()
    description = str(args.get("description") or "")
    with ctx.db_factory() as db:
        row = projects.create_project(db, name, description)
        text = f"Created project {row.name} at {row.folder}"
    return ToolResult(True, text)


def log_action(db: Session, tool_name: str, arguments: dict, status: str, result: str) -> None:
    payload = json.dumps(arguments, default=str)[:4000]
    db.add(
        ActionLog(
            tool_name=tool_name,
            arguments_json=payload,
            status=status,
            result=(result or "")[:8000],
            created_at=utcnow(),
        )
    )
    db.flush()
