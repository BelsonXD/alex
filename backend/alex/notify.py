"""Desktop notifications for reminders. Windows uses a balloon tip, not a web toast."""

from __future__ import annotations

import logging
import platform
import subprocess

log = logging.getLogger("alex.notify")


def notify(title: str, body: str) -> str:
    system = platform.system()
    safe_title = (title or "ALEX").replace("'", "''")
    safe_body = (body or "").replace("'", "''")[:240]
    try:
        if system == "Windows":
            script = (
                "Add-Type -AssemblyName System.Windows.Forms; "
                "Add-Type -AssemblyName System.Drawing; "
                "$n = New-Object System.Windows.Forms.NotifyIcon; "
                "$n.Icon = [System.Drawing.SystemIcons]::Information; "
                f"$n.BalloonTipTitle = '{safe_title}'; "
                f"$n.BalloonTipText = '{safe_body}'; "
                "$n.Visible = $true; $n.ShowBalloonTip(8000)"
            )
            subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=0x08000000,
            )
            return "windows"
        if system == "Darwin":
            subprocess.run(
                ["osascript", "-e", f'display notification "{safe_body}" with title "{safe_title}"'],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return "macos"
        subprocess.run(["notify-send", safe_title, safe_body], capture_output=True, text=True, timeout=10)
        return "linux"
    except Exception as exc:  # noqa: BLE001
        log.info("desktop notification skipped: %s", exc)
        return f"skipped: {exc}"
