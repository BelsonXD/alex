#!/usr/bin/env python3
"""Start ALEX and open it in the browser. Works on Windows, macOS, and Linux."""

from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    from alex.pycompat import ensure_supported_or_exit

    ensure_supported_or_exit()
    import uvicorn

    from alex.config import get_settings

    settings = get_settings()
    host = settings.alex_host or "127.0.0.1"
    port = int(settings.alex_port)
    page = f"http://127.0.0.1:{port}"

    def open_when_ready() -> None:
        if os.environ.get("ALEX_NO_BROWSER") == "1":
            return
        health = page + "/api/health"
        for _ in range(60):
            try:
                import urllib.request

                with urllib.request.urlopen(health, timeout=0.5) as response:
                    if response.status == 200:
                        break
            except Exception:
                time.sleep(0.25)
        try:
            webbrowser.open(page)
        except Exception:
            print(f"Open {page} in your browser.")

    threading.Thread(target=open_when_ready, daemon=True).start()
    print(f"ALEX is starting at {page}")
    print("Close this window, or press Ctrl+C, to stop ALEX.")
    uvicorn.run("alex.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
