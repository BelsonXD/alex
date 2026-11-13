"""Tools run only after approval, and a denial does not touch the machine."""

from __future__ import annotations

import sys

from alex.llm.offline import plan_offline


def _drain(ws, stop_at=("done", "error")):
    messages = []
    while True:
        message = ws.receive_json()
        messages.append(message)
        if message["type"] in stop_at:
            return messages


def test_offline_reads_attached_documents_and_flags_images():
    notes = plan_offline("What does the note say?\n\n[Attached file: notes.txt]\nCoil temperature is stable.")
    assert notes.tool is None
    assert "Coil temperature is stable." in (notes.text or "")
    image = plan_offline(
        "Describe this.\n\n[Image attached: core.png. This model is not marked as vision-capable, so the pixels were not sent.]"
    )
    assert "cannot see pixels" in (image.text or "")


def test_offline_plans_powershell_and_files():
    command = plan_offline("Run this PowerShell command: Get-Date")
    assert command.tool == "run_command"
    assert command.args["command"] == "Get-Date"
    reminder = plan_offline("Remind me in 2 minutes to inspect the core")
    assert reminder.tool == "create_reminder"
    assert reminder.args["due_in_seconds"] == 120
    written = plan_offline("Create a file called hello.py that prints hello")
    assert written.tool == "write_file"
    assert written.args["path"] == "hello.py"
    assert "hello" in written.args["content"]


def test_denied_command_does_not_run(client, tmp_path):
    marker = tmp_path / "should-not-exist.txt"
    script = f"open(r'{marker.as_posix()}','w').write('ran')"
    content = f'Run the command {sys.executable} -c "{script}"'
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "chat", "content": content})
        approval = None
        while approval is None:
            message = ws.receive_json()
            if message["type"] == "error":
                raise AssertionError(message)
            if message["type"] == "approval_required":
                approval = message
        assert approval["tool"] == "run_command"
        assert "user account" in approval["risk"]
        ws.send_json({"type": "approval_decision", "approval_id": approval["approval_id"], "approved": False})
        rest = _drain(ws)
    assert marker.exists() is False
    assert any(item["type"] == "tool_result" and item["ok"] is False for item in rest)
    actions = client.get("/api/actions").json()
    assert actions[0]["status"] == "denied"


def test_approved_command_runs_and_is_logged(client, tmp_path):
    marker = tmp_path / "did-run.txt"
    script = f"open(r'{marker.as_posix()}','w').write('ALEX-OK')"
    content = f'Run the command {sys.executable} -c "{script}"'
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "chat", "content": content})
        approval_id = None
        while approval_id is None:
            message = ws.receive_json()
            if message["type"] == "approval_required":
                approval_id = message["approval_id"]
                assert sys.executable in message["summary"]
            elif message["type"] == "error":
                raise AssertionError(message)
        ws.send_json({"type": "approval_decision", "approval_id": approval_id, "approved": True})
        rest = _drain(ws)
    assert marker.read_text(encoding="utf-8") == "ALEX-OK"
    result = next(item for item in rest if item["type"] == "tool_result")
    assert result["ok"] is True
    assert "exit 0" in result["output"]
    assert client.get("/api/actions").json()[0]["status"] == "executed"


def test_allowlist_skips_approval(client, tmp_path):
    updated = client.put("/api/settings", json={"command_allowlist": [sys.executable]})
    assert updated.status_code == 200
    marker = tmp_path / "allowed.txt"
    script = f"open(r'{marker.as_posix()}','w').write('yes')"
    content = f'Run the command {sys.executable} -c "{script}"'
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "chat", "content": content})
        messages = _drain(ws)
    assert marker.read_text(encoding="utf-8") == "yes"
    assert not any(item["type"] == "approval_required" for item in messages)


def test_write_file_needs_approval_and_stays_in_sandbox(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "chat", "content": "Create a file called hello.py that prints hello"})
        approval = None
        while approval is None:
            message = ws.receive_json()
            if message["type"] == "approval_required":
                approval = message
            elif message["type"] in {"done", "error"}:
                raise AssertionError(messages_so_far(message))
        assert approval["tool"] == "write_file"
        ws.send_json({"type": "approval_decision", "approval_id": approval["approval_id"], "approved": True})
        _drain(ws)
    sandbox = client.get("/api/system/status").json()["safe_folders"][0]
    written = __import__("pathlib").Path(sandbox) / "hello.py"
    assert written.exists()
    assert "hello" in written.read_text(encoding="utf-8")


def messages_so_far(message):
    return message


def test_list_files_needs_no_approval(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "chat", "content": "List files in sandbox"})
        messages = _drain(ws)
    assert any(item["type"] == "tool_result" and item["name"] == "list_files" and item["ok"] for item in messages)
    assert not any(item["type"] == "approval_required" for item in messages)
