"""Host computer control.

Windows is the primary target: commands run in PowerShell, applications open
through Start-Process and the Start menu (Get-StartApps), and paths accept
Windows drive letters, backslashes, and %ENV% variables.

macOS and Linux stay supported with bash and the platform open command.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000


def host_system(system: str | None = None) -> str:
    return system or platform.system()


def shell_name(system: str | None = None) -> str:
    return "PowerShell" if host_system(system) == "Windows" else "bash"


def default_alex_root() -> Path:
    """Project files live beside the database, outside the unzipped app."""
    override = os.environ.get("ALEX_HOME", "").strip()
    if override:
        return Path(expand_user_path(override))
    from alex.config import default_user_data_dir

    return default_user_data_dir() / "Projects"


def expand_user_path(raw: str) -> str:
    """Expand ~, $VARS, and Windows %VARS% on every host."""
    text = (raw or "").strip().strip('"').strip("'")

    def windows_var(match: re.Match[str]) -> str:
        return os.environ.get(match.group(1), match.group(0))

    text = os.path.expandvars(text)
    text = re.sub(r"%([^%]+)%", windows_var, text)
    return os.path.expanduser(text)


def is_within(path: Path, root: Path) -> bool:
    try:
        resolved = path.resolve()
        root_resolved = root.resolve()
    except OSError:
        return False
    probe = os.path.normcase(os.path.normpath(str(resolved)))
    base = os.path.normcase(os.path.normpath(str(root_resolved)))
    if probe == base:
        return True
    separator = os.sep
    if not base.endswith(separator):
        base = base + separator
    return probe.startswith(base)


def resolve_inside(raw: str, roots: list[Path]) -> Path:
    """Resolve a user path and require it to sit inside a safe folder."""
    if not roots:
        raise PermissionError("No safe folders are configured. Add one in Settings.")
    expanded = expand_user_path(raw)
    path = Path(expanded)
    if not path.is_absolute():
        path = (roots[0] / path).resolve()
    else:
        path = path.resolve()
    for root in roots:
        if is_within(path, root):
            return path
    readable = ", ".join(str(root) for root in roots)
    raise PermissionError(f"Path is outside the safe folders ({readable}): {path}")


def ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def prepare_command(command: str, system: str | None = None) -> str:
    command = command.strip()
    if host_system(system) == "Windows":
        # Force UTF-8 so Python captures Unicode paths and output on Windows.
        return (
            "$ProgressPreference='SilentlyContinue'; "
            "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); "
            "$OutputEncoding=[Console]::OutputEncoding; "
            + command
        )
    return command


def build_shell_argv(command: str, system: str | None = None) -> list[str]:
    system = host_system(system)
    wrapped = prepare_command(command, system)
    if system == "Windows":
        return ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", wrapped]
    return ["bash", "-c", wrapped]


def windows_open_app_script(name: str) -> str:
    """PowerShell that tries App Paths first, then the Start menu catalog."""
    quoted = ps_quote(name)
    return f"""
$ErrorActionPreference = 'Stop'
$name = {quoted}
try {{
  Start-Process -FilePath $name
  Write-Output "Opened $name"
  exit 0
}} catch {{
}}
$app = Get-StartApps | Where-Object {{ $_.Name -eq $name -or $_.Name -like ('*' + $name + '*') }} | Select-Object -First 1
if ($null -eq $app) {{
  Write-Error "Could not find an application named $name. Try the .exe name, for example notepad, or the name shown in the Start menu."
  exit 1
}}
Start-Process ("shell:AppsFolder\\" + $app.AppID)
Write-Output ("Opened " + $app.Name)
"""


def build_open_app_argv(name: str, system: str | None = None) -> list[str]:
    system = host_system(system)
    if system == "Windows":
        return [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            windows_open_app_script(name),
        ]
    if system == "Darwin":
        return ["open", "-a", name]
    desktop = shutil.which(name)
    if desktop:
        return [desktop]
    return ["xdg-open", name]


def build_open_url_argv(url: str, system: str | None = None) -> list[str]:
    system = host_system(system)
    if system == "Windows":
        return ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", f"Start-Process {ps_quote(url)}"]
    if system == "Darwin":
        return ["open", url]
    return ["xdg-open", url]


def build_open_folder_argv(path: str, system: str | None = None) -> list[str]:
    system = host_system(system)
    if system == "Windows":
        return ["explorer.exe", path]
    if system == "Darwin":
        return ["open", path]
    return ["xdg-open", path]


def child_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def run_process(argv: list[str], cwd: Path | None, timeout: int, system: str | None = None) -> subprocess.CompletedProcess[str]:
    system = host_system(system)
    kwargs: dict = {
        "cwd": str(cwd) if cwd else None,
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": timeout,
        "env": child_env(),
    }
    if system == "Windows":
        kwargs["creationflags"] = CREATE_NO_WINDOW
    return subprocess.run(argv, **kwargs)


def format_process(proc: subprocess.CompletedProcess[str], limit: int = 16000) -> tuple[bool, str]:
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    parts = [f"exit {proc.returncode}"]
    if stdout:
        parts.append("stdout:\n" + stdout)
    if stderr:
        parts.append("stderr:\n" + stderr)
    if len(parts) == 1:
        parts.append("(no output)")
    text = "\n".join(parts)
    if len(text) > limit:
        text = text[:limit] + "\n…truncated…"
    return proc.returncode == 0, text


def special_folder(name: str, sandbox: Path) -> Path | None:
    key = (name or "").strip().lower()
    home = Path.home()
    aliases = {
        "sandbox": sandbox,
        "home": home,
        "desktop": _first_existing([home / "Desktop", home / "OneDrive" / "Desktop"], home / "Desktop"),
        "documents": _first_existing(
            [home / "Documents", home / "OneDrive" / "Documents"],
            home / "Documents",
        ),
        "downloads": _first_existing(
            [home / "Downloads", home / "OneDrive" / "Downloads"],
            home / "Downloads",
        ),
    }
    return aliases.get(key)


def _first_existing(candidates: list[Path], fallback: Path) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return fallback
