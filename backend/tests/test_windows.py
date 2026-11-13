"""Windows is the primary host. These tests lock the PowerShell and path behavior."""

import os

import pytest

from alex.tools.computer import (
    build_open_app_argv,
    build_open_folder_argv,
    build_open_url_argv,
    build_shell_argv,
    expand_user_path,
    is_within,
    resolve_inside,
    shell_name,
    windows_open_app_script,
)


def test_windows_shell_is_powershell():
    argv = build_shell_argv("Get-ChildItem C:\\Users", system="Windows")
    assert argv[0] == "powershell.exe"
    assert "-Command" in argv
    assert "Get-ChildItem C:\\Users" in argv[-1]
    assert "OutputEncoding" in argv[-1]
    assert shell_name("Windows") == "PowerShell"


def test_unix_shell_is_bash():
    argv = build_shell_argv("ls -la", system="Linux")
    assert argv[:2] == ["bash", "-c"]
    assert argv[-1] == "ls -la"


def test_windows_open_app_uses_start_menu():
    script = windows_open_app_script("Visual Studio Code")
    assert "Start-Process" in script
    assert "Get-StartApps" in script
    assert "shell:AppsFolder" in script
    assert "Visual Studio Code" in script
    argv = build_open_app_argv("notepad", system="Windows")
    assert argv[0] == "powershell.exe"
    assert "notepad" in argv[-1]


def test_windows_quoting_escapes_single_quotes():
    script = windows_open_app_script("Sahib's Notes")
    assert "Sahib''s Notes" in script


def test_open_url_and_folder_are_platform_specific():
    assert build_open_url_argv("https://example.com", system="Windows")[0] == "powershell.exe"
    assert build_open_url_argv("https://example.com", system="Darwin") == ["open", "https://example.com"]
    assert build_open_folder_argv(r"C:\Users\Sahib\Documents\ALEX", system="Windows")[0] == "explorer.exe"
    assert build_open_folder_argv("/tmp", system="Linux")[0] == "xdg-open"


def test_env_and_user_path_expansion(monkeypatch, tmp_path):
    monkeypatch.setenv("ALEX_TEST_DIR", str(tmp_path))
    expanded = expand_user_path(os.path.join("%ALEX_TEST_DIR%", "notes"))
    assert expanded.startswith(str(tmp_path))


def test_safe_folder_rejects_escape(tmp_path):
    root = tmp_path / "safe"
    root.mkdir()
    inside = resolve_inside("notes/hello.txt", [root])
    assert is_within(inside, root)
    with pytest.raises(PermissionError):
        resolve_inside("../outside.txt", [root])
    with pytest.raises(PermissionError):
        resolve_inside(str(tmp_path / "secret.txt"), [root])
