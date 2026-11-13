"""Check a manifest or a GitHub release, then replace the app folder in place.

User data (%LOCALAPPDATA%\\ALEX, or the Linux/macOS equivalent) is outside the
install folder, so .env, the database, memories, and project records stay put.
If the new files fail to install, the previous files are copied back.
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import httpx

from alex import __version__
from alex.config import ROOT, get_settings

SKIP_PARTS = {".venv", "venv", "node_modules", "__pycache__", ".git", "data"}


def parse_version(value: str) -> tuple[int, ...]:
    text = (value or "").strip().lstrip("vV")
    parts: list[int] = []
    for piece in text.split("."):
        number = ""
        for char in piece:
            if char.isdigit():
                number += char
            else:
                break
        if number == "":
            break
        parts.append(int(number))
    return tuple(parts) or (0,)


def is_newer(remote: str, local: str | None = None) -> bool:
    return parse_version(remote) > parse_version(local or __version__)


async def check_for_update() -> dict[str, Any]:
    settings = get_settings()
    local = __version__
    base = {
        "version": local,
        "data_dir": str(settings.data_path),
        "update_available": False,
        "configured": bool(settings.alex_update_manifest.strip() or settings.alex_github_repo.strip()),
        "latest": local,
        "notes": "",
        "zip_url": "",
        "sha256": "",
        "detail": "",
    }
    if not base["configured"]:
        base["detail"] = _setup_help()
        return base
    try:
        offer = await _fetch_offer(settings.alex_update_manifest.strip(), settings.alex_github_repo.strip(), settings.alex_update_token.strip())
    except Exception as exc:  # noqa: BLE001
        base["detail"] = f"Could not check for an update: {exc}"
        return base
    base["latest"] = offer["version"]
    base["notes"] = offer["notes"]
    base["zip_url"] = offer["zip_url"]
    base["sha256"] = offer.get("sha256") or ""
    if is_newer(offer["version"], local):
        base["update_available"] = True
        base["detail"] = f"Version {offer['version']} is available. You are running {local}."
    else:
        base["detail"] = f"ALEX {local} is the newest published version."
    return base


def _setup_help() -> str:
    return (
        "Updates are not configured yet. This copy can update itself after you publish it once. "
        "Create a public GitHub repository, add a Release, and attach a file named alex.zip. "
        "Then set ALEX_GITHUB_REPO to owner/name in Settings. "
        "If the repository is private, also set ALEX_UPDATE_TOKEN to a fine-grained token with Contents: Read. "
        "Or host manifest.json with version, zip_url, sha256, and notes, and set ALEX_UPDATE_MANIFEST to that URL. "
        "Your keys, database, memories, and projects stay in the user data folder and are not replaced."
    )


async def _fetch_offer(manifest: str, repo: str, token: str) -> dict[str, str]:
    headers = {"User-Agent": "ALEX", "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        if manifest:
            response = await client.get(manifest, headers=headers)
            response.raise_for_status()
            data = response.json()
            if "zip_url" not in data or "version" not in data:
                raise RuntimeError("The manifest needs version and zip_url.")
            return {
                "version": str(data["version"]).lstrip("vV"),
                "zip_url": str(data["zip_url"]),
                "sha256": str(data.get("sha256") or ""),
                "notes": str(data.get("notes") or data.get("changelog") or ""),
            }
        response = await client.get(f"https://api.github.com/repos/{repo}/releases/latest", headers=headers)
        if response.status_code == 404:
            raise RuntimeError(
                f"No GitHub release found for {repo}. Publish a release and attach alex.zip, "
                "or set ALEX_UPDATE_MANIFEST."
            )
        response.raise_for_status()
        data = response.json()
        asset = next((item for item in data.get("assets") or [] if item.get("name") == "alex.zip"), None)
        if asset is None:
            raise RuntimeError("The latest GitHub release has no alex.zip asset. Attach that exact filename.")
        zip_url = str(asset.get("url") if token else asset.get("browser_download_url") or asset.get("url"))
        return {
            "version": str(data.get("tag_name") or "").lstrip("vV"),
            "zip_url": zip_url,
            "sha256": "",
            "notes": str(data.get("body") or ""),
        }


async def download_zip(url: str, dest: Path, token: str, sha256: str) -> None:
    headers = {"User-Agent": "ALEX"}
    if token and ("api.github.com" in url or "codeload.github.com" in url):
        headers["Authorization"] = f"Bearer {token}"
        headers["Accept"] = "application/octet-stream"
    dest.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        async with client.stream("GET", url, headers=headers) as response:
            response.raise_for_status()
            with dest.open("wb") as handle:
                async for chunk in response.aiter_bytes():
                    handle.write(chunk)
                    digest.update(chunk)
    if sha256 and digest.hexdigest().lower() != sha256.lower():
        dest.unlink(missing_ok=True)
        raise RuntimeError("The downloaded zip did not match the published sha256. Nothing was changed.")


def _skipped(relative: Path) -> bool:
    return any(part in SKIP_PARTS for part in relative.parts) or relative.name == ".env"


def _files(root: Path) -> set[str]:
    found: set[str] = set()
    if not root.exists():
        return found
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if _skipped(relative):
            continue
        found.add(relative.as_posix())
    return found


def _copy_files(source: Path, dest: Path) -> None:
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        if _skipped(relative):
            continue
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def safe_extract(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as handle:
        for info in handle.infolist():
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or name.startswith("../") or "/../" in f"/{name}":
                raise RuntimeError(f"The update zip contains an unsafe path: {info.filename}")
            pure = Path(name)
            if ".." in pure.parts:
                raise RuntimeError(f"The update zip contains an unsafe path: {info.filename}")
        handle.extractall(dest)


def _hash_file(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hash_tree(root: Path, folder: str) -> str:
    base = root / folder
    digest = hashlib.sha256()
    if not base.exists():
        return ""
    for path in sorted(p for p in base.rglob("*") if p.is_file() and not _skipped(p.relative_to(root))):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def apply_zip(
    archive: Path,
    install: Path | None = None,
    *,
    run_deps: bool = True,
    restart: bool = False,
) -> dict[str, Any]:
    install = install or ROOT
    staging = archive.parent / (archive.stem + "-staging")
    rollback = archive.parent / (archive.stem + "-rollback")
    if staging.exists():
        shutil.rmtree(staging)
    if rollback.exists():
        shutil.rmtree(rollback)
    safe_extract(archive, staging)
    if not (staging / "start.py").exists() or not (staging / "backend" / "alex" / "__init__.py").exists():
        shutil.rmtree(staging, ignore_errors=True)
        raise RuntimeError("The update zip is not an ALEX build. The installed copy was left unchanged.")

    before = _files(install)
    rollback.mkdir(parents=True, exist_ok=True)
    _copy_files(install, rollback)
    old_requirements = _hash_file(install / "requirements.txt")
    old_frontend = _hash_tree(install, "frontend")
    log: list[str] = ["Saved the current files for rollback."]
    try:
        _copy_files(staging, install)
        new_files = _files(install)
        for relative in new_files - before - _files(staging):
            pass
        log.append("Copied the new version into the install folder.")
        if run_deps and _hash_file(install / "requirements.txt") != old_requirements:
            _pip_install(install)
            log.append("Installed changed Python packages from wheels.")
        elif run_deps:
            log.append("Python packages were already current.")
        if run_deps and _hash_tree(install, "frontend") != old_frontend:
            _npm_build(install)
            log.append("Rebuilt the interface.")
        elif run_deps:
            log.append("The interface did not need a rebuild.")
        if not (install / "start.py").exists():
            raise RuntimeError("start.py disappeared during the update.")
    except Exception as exc:
        _copy_files(rollback, install)
        restored = _files(install)
        for relative in list(restored - before):
            target = install / relative
            if target.exists() and target.is_file():
                target.unlink()
        log.append(f"Update failed ({exc}). Restored the previous files.")
        shutil.rmtree(staging, ignore_errors=True)
        raise RuntimeError(log[-1]) from exc
    shutil.rmtree(staging, ignore_errors=True)
    if restart:
        _spawn_restart(install)
        log.append("Restarting ALEX.")
    return {"ok": True, "log": log}


def _pip_install(install: Path) -> None:
    system = platform.system()
    venv_python = install / ".venv" / ("Scripts/python.exe" if system == "Windows" else "bin/python")
    python = str(venv_python if venv_python.exists() else Path(sys.executable))
    command = [python, "-m", "pip", "install", "--disable-pip-version-check", "--prefer-binary", "-r", "requirements.txt"]
    completed = subprocess.run(command, cwd=str(install), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "pip failed")[:800])


def _npm_build(install: Path) -> None:
    frontend = install / "frontend"
    npm = shutil.which("npm.cmd" if platform.system() == "Windows" else "npm") or shutil.which("npm")
    if npm is None:
        raise RuntimeError("Node.js is not on PATH, so the interface could not be rebuilt. Install it from https://nodejs.org/en/download")
    lock = frontend / "package-lock.json"
    install_cmd = [npm, "ci"] if lock.exists() else [npm, "install"]
    for command in (install_cmd, [npm, "run", "build"]):
        completed = subprocess.run(command, cwd=str(frontend), capture_output=True, text=True, encoding="utf-8", errors="replace")
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout or "npm failed")[:800])


def _spawn_restart(install: Path) -> None:
    if platform.system() == "Windows":
        script = install / "_alex_restart.bat"
        script.write_text(
            "@echo off\r\n"
            "timeout /t 2 /nobreak >nul\r\n"
            f"cd /d \"{install}\"\r\n"
            "call start.bat\r\n",
            encoding="utf-8",
        )
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(["cmd", "/c", str(script)], cwd=str(install), creationflags=flags, close_fds=True)
        return
    script = install / "_alex_restart.sh"
    launcher = install / "start.sh"
    script.write_text(f"#!/bin/sh\nsleep 2\ncd \"{install}\"\nexec \"{launcher}\"\n", encoding="utf-8")
    os.chmod(script, 0o755)
    subprocess.Popen(["sh", str(script)], cwd=str(install), start_new_session=True)


def offer_from_status(status: dict[str, Any]) -> bool:
    return bool(status.get("update_available"))
