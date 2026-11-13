"""Isolated data directory and a fresh app for every test."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

SECRET_KEYS = [
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "ELEVENLABS_API_KEY",
    "ELEVENLABS_VOICE_ID",
    "TAVILY_API_KEY",
    "BRAVE_SEARCH_API_KEY",
]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ALEX_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ALEX_HOME", str(tmp_path / "ALEX"))
    monkeypatch.setenv("ALEX_ENV_FILE", str(tmp_path / ".env"))
    monkeypatch.setenv("ALEX_PROVIDER", "offline")
    monkeypatch.setenv("ALEX_DISABLE_SCHEDULER", "1")
    monkeypatch.setenv("ALEX_DISABLE_UPDATE_CHECK", "1")
    for key in SECRET_KEYS:
        monkeypatch.setenv(key, "")

    from alex.config import get_settings

    get_settings.cache_clear()
    from alex.database import reset_engine

    reset_engine()
    from alex.llm.providers import reset_router

    reset_router()
    from alex.main import create_app

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()
