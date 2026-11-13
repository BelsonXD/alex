"""Projects, reminders, uploads, voice capabilities, and settings."""

from __future__ import annotations

import asyncio

from alex.automations.scheduler import process_due


def test_health_persona_and_secret_is_not_echoed(client, tmp_path):
    health = client.get("/api/health").json()
    assert health["ok"] is True
    renamed = client.put(
        "/api/settings",
        json={"assistant_name": "ALEX", "persona": "Speak precisely to Sahib."},
    )
    assert renamed.status_code == 200
    assert "Speak precisely" in renamed.json()["persona"]
    saved = client.post("/api/settings/secrets", json={"openai_api_key": "sk-test-secret"})
    assert saved.status_code == 200
    assert saved.json()["keys"]["openai"] is True
    body = client.get("/api/settings").text
    assert "sk-test-secret" not in body
    env_file = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "sk-test-secret" in env_file


def test_project_workspace_and_upload(client):
    project = client.post("/api/projects", json={"name": "Arc Reactor", "description": "Bench notes"}).json()
    assert project["folder"]
    listing = client.get(f"/api/projects/{project['id']}/files").json()
    assert listing["files"] == []
    upload = client.post(
        "/api/uploads",
        files={"file": ("notes.txt", b"Coil temperature is stable.", "text/plain")},
    )
    assert upload.status_code == 200
    attachment_id = upload.json()["id"]
    with client.websocket_connect("/ws") as ws:
        ws.send_json(
            {
                "type": "chat",
                "content": "What does the note say?",
                "project_id": project["id"],
                "attachment_ids": [attachment_id],
            }
        )
        conversation_id = None
        while True:
            message = ws.receive_json()
            if message["type"] == "conversation":
                conversation_id = message["conversation_id"]
            if message["type"] in {"done", "error"}:
                break
    messages = client.get(f"/api/conversations/{conversation_id}/messages").json()
    user = next(item for item in messages if item["role"] == "user")
    assert "Coil temperature is stable." in user["content"]
    assert client.get("/api/conversations").json()[0]["project_name"] == "Arc Reactor"


def test_reminder_fires_and_automation_runs(client):
    created = client.post(
        "/api/reminders",
        json={"title": "Inspect the core", "notes": "Look at the reactor", "due_at": "2020-01-01T00:00:00+00:00"},
    )
    assert created.status_code == 200
    notes = asyncio.run(process_due(client.app))
    assert any(note["title"] == "Inspect the core" for note in notes)
    listed = client.get("/api/reminders").json()
    assert listed[0]["status"] == "fired"
    notifications = client.get("/api/notifications").json()
    assert notifications[0]["kind"] == "reminder"

    automation = client.post(
        "/api/automations",
        json={"name": "Clock", "prompt": "what time is it", "interval_seconds": 3600},
    ).json()
    ran = client.post(f"/api/automations/{automation['id']}/run")
    assert ran.status_code == 200
    assert "Local:" in ran.json()["last_result"]


def test_docx_upload_extracts_text(client, tmp_path):
    from docx import Document

    path = tmp_path / "note.docx"
    document = Document()
    document.add_paragraph("The coil is nominal.")
    document.save(path)
    upload = client.post("/api/uploads", files={"file": ("note.docx", path.read_bytes(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
    assert upload.status_code == 200
    assert "nominal" in upload.json()["excerpt"]


def test_manifest_reports_a_newer_version(client, monkeypatch):
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from alex.config import get_settings

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = json.dumps(
                {
                    "version": "9.9.9",
                    "zip_url": "http://127.0.0.1/alex-9.9.9.zip",
                    "notes": "Simulated changelog: calmer core and a clearer update dialog.",
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):  # noqa: A003
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("ALEX_UPDATE_MANIFEST", f"http://127.0.0.1:{server.server_address[1]}/manifest.json")
        get_settings.cache_clear()
        status = client.get("/api/system/update").json()
    finally:
        server.shutdown()
        get_settings.cache_clear()
    assert status["update_available"] is True
    assert status["latest"] == "9.9.9"
    assert status["version"] == "1.1.2"
    assert "Simulated changelog" in status["notes"]


def test_update_check_explains_setup_when_unconfigured(client):
    status = client.get("/api/system/update").json()
    assert status["version"]
    assert status["update_available"] is False
    assert "alex.zip" in status["detail"]
    assert status["data_dir"]


def test_voice_without_keys_asks_for_the_browser(client):
    caps = client.get("/api/voice/capabilities").json()
    assert caps["stt"] == "browser"
    assert caps["tts"] == "browser"
    spoken = client.post("/api/voice/speak", json={"text": "ALEX online."})
    assert spoken.status_code == 409
    assert spoken.json()["fallback"] == "browser"
    tools = client.get("/api/tools").json()
    assert any(tool["name"] == "text_utility" for tool in tools)
    assert any(tool["name"] == "run_command" and tool["needs_approval"] for tool in tools)
