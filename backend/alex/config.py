"""Environment-backed configuration. Secrets stay in .env, never in code."""

from __future__ import annotations

import os
import platform
import shutil
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]

DEFAULT_PERSONA = """You are ALEX, Sahib's personal AI, running locally on his computer. You are calm, exact, and quietly loyal in the way a chief of staff is loyal: you protect his attention, you tell the truth about what you actually did, and you prefer a working result over a performance.

Speak in clear sentences. Use technical language when it helps and plain language when it does not. Dry wit is welcome. Filler is not. Address him as Sahib.

You can remember facts, search the web, read and organize files inside his safe folders, draft and save code into a project, set reminders, and — only after he approves — run PowerShell, change files, or open applications. Never invent tool results. If an API key or a model is missing, say which setting fixes it.

When Sahib teaches you something that will still matter next week, store it with the remember tool. When a task is ambiguous, make the safest reasonable assumption and name it."""

KEY_HELP = {
    "openai": "https://platform.openai.com/api-keys",
    "anthropic": "https://console.anthropic.com/settings/keys",
    "xai": "https://console.x.ai/",
    "elevenlabs": "https://elevenlabs.io/app/settings/api-keys",
    "tavily": "https://tavily.com",
    "brave": "https://api.search.brave.com/app/keys",
    "ollama": "https://ollama.com/download/windows",
}

DEFAULT_MODELS = {
    "offline": "alex-kernel",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-4-5",
    "xai": "grok-3",
    "ollama": "llama3.2",
}

MODEL_CHOICES = {
    "offline": ["alex-kernel"],
    "openai": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"],
    "anthropic": ["claude-sonnet-4-5", "claude-3-5-haiku-latest", "claude-3-5-sonnet-latest"],
    "xai": ["grok-3", "grok-3-mini", "grok-2-latest"],
    "ollama": ["llama3.2", "llama3.1", "mistral", "llava"],
}


class Settings(BaseSettings):
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    xai_api_key: str = ""
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    tavily_api_key: str = ""
    brave_search_api_key: str = ""
    ollama_base_url: str = "http://127.0.0.1:11434"
    alex_provider: str = "offline"
    alex_model: str = ""
    alex_host: str = "127.0.0.1"
    alex_port: int = 8787
    alex_data_dir: str = ""
    alex_github_repo: str = ""
    alex_update_manifest: str = ""
    alex_update_token: str = ""

    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def data_path(self) -> Path:
        explicit = os.environ.get("ALEX_DATA_DIR", "").strip() or (self.alex_data_dir or "").strip()
        if explicit:
            path = Path(explicit).expanduser()
            if not path.is_absolute():
                path = ROOT / path
            return path
        return default_user_data_dir()

    @property
    def database_path(self) -> Path:
        return self.data_path / "alex.db"

    @property
    def env_path(self) -> Path:
        return resolve_env_file()


def default_user_data_dir(system: str | None = None) -> Path:
    """Stable folder outside the unzipped app. Updates never replace it."""
    system = system or platform.system()
    if system == "Windows":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "ALEX"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "ALEX"
    return Path.home() / ".local" / "share" / "alex"


def resolve_env_file() -> Path:
    override = os.environ.get("ALEX_ENV_FILE", "").strip()
    if override:
        path = Path(override).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    data = default_user_data_dir()
    data.mkdir(parents=True, exist_ok=True)
    target = data / ".env"
    legacy = ROOT / ".env"
    if not target.exists() and legacy.exists():
        shutil.copy2(legacy, target)
    if not target.exists() and (ROOT / ".env.example").exists():
        shutil.copy2(ROOT / ".env.example", target)
    return target


def migrate_legacy_install() -> None:
    """Copy a database that lived inside the app folder into the user data folder once."""
    if os.environ.get("ALEX_DATA_DIR", "").strip():
        return
    target = default_user_data_dir()
    legacy = ROOT / "data"
    if not legacy.exists():
        return
    target.mkdir(parents=True, exist_ok=True)
    legacy_db = legacy / "alex.db"
    dest_db = target / "alex.db"
    if legacy_db.exists() and not dest_db.exists():
        shutil.copy2(legacy_db, dest_db)
    for name in ("uploads", "sandbox"):
        source = legacy / name
        dest = target / name
        if source.is_dir() and not dest.exists():
            shutil.copytree(source, dest)


@lru_cache
def get_settings() -> Settings:
    return Settings(_env_file=str(resolve_env_file()))


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


def write_env_values(updates: dict[str, str], env_path: Path | None = None) -> None:
    """Update keys in the .env file. Values are strings. Empty string clears a key."""
    path = env_path or get_settings().env_path
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    remaining = dict(updates)
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            new_lines.append(line)
            continue
        key = line.split("=", 1)[0]
        if key in remaining:
            new_lines.append(f"{key}={_escape_env(remaining.pop(key))}")
        else:
            new_lines.append(line)
    for key, value in remaining.items():
        new_lines.append(f"{key}={_escape_env(value)}")
    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    for key, value in updates.items():
        os.environ[key] = value


def _escape_env(value: str) -> str:
    if any(ch in value for ch in " #\t\n\r\"'"):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "")
        return f'"{escaped}"'
    return value


def apply_runtime_keys(updates: dict[str, str]) -> Settings:
    """Persist keys and refresh the cached settings object."""
    env_map = {
        "openai_api_key": "OPENAI_API_KEY",
        "anthropic_api_key": "ANTHROPIC_API_KEY",
        "xai_api_key": "XAI_API_KEY",
        "elevenlabs_api_key": "ELEVENLABS_API_KEY",
        "elevenlabs_voice_id": "ELEVENLABS_VOICE_ID",
        "tavily_api_key": "TAVILY_API_KEY",
        "brave_search_api_key": "BRAVE_SEARCH_API_KEY",
        "ollama_base_url": "OLLAMA_BASE_URL",
        "alex_github_repo": "ALEX_GITHUB_REPO",
        "alex_update_manifest": "ALEX_UPDATE_MANIFEST",
        "alex_update_token": "ALEX_UPDATE_TOKEN",
    }
    file_updates = {env_map[k]: v for k, v in updates.items() if k in env_map}
    if file_updates:
        write_env_values(file_updates)
    settings = get_settings()
    for key, value in updates.items():
        if hasattr(settings, key):
            setattr(settings, key, value)
    return settings
