"""Screenshots and pointer control. Windows DPI is mapped into one coordinate space."""

from __future__ import annotations

import base64
import io
import os
import platform
import shutil
import subprocess
import tempfile
import threading
from typing import Any

_dpi_ready = False
_stop_hotkey = None


def prepare_windows_dpi() -> float:
    """Make this process per-monitor DPI aware so mss and pyautogui share pixels."""
    global _dpi_ready
    if platform.system() != "Windows":
        return 1.0
    import ctypes

    if not _dpi_ready:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
        _dpi_ready = True
    try:
        hdc = ctypes.windll.user32.GetDC(0)
        dpi = int(ctypes.windll.gdi32.GetDeviceCaps(hdc, 88))
        ctypes.windll.user32.ReleaseDC(0, hdc)
        if dpi > 0:
            return dpi / 96.0
    except Exception:
        return 1.0
    return 1.0


def map_image_point(
    x: float,
    y: float,
    image_w: int,
    image_h: int,
    screen_w: int,
    screen_h: int,
    origin_x: int = 0,
    origin_y: int = 0,
) -> tuple[int, int]:
    if image_w <= 0 or image_h <= 0:
        return int(x), int(y)
    px = origin_x + (float(x) / float(image_w)) * float(screen_w)
    py = origin_y + (float(y) / float(image_h)) * float(screen_h)
    return int(round(px)), int(round(py))


def map_screen_to_pointer(
    x: int,
    y: int,
    screen_w: int,
    screen_h: int,
    pointer_w: int,
    pointer_h: int,
) -> tuple[int, int]:
    if screen_w <= 0 or screen_h <= 0:
        return x, y
    return int(round(x * pointer_w / screen_w)), int(round(y * pointer_h / screen_h))


def _grab_image():
    from PIL import Image

    try:
        import mss

        with mss.mss() as sct:
            monitor = sct.monitors[1]
            raw = sct.grab(monitor)
            image = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
            return image, int(monitor["left"]), int(monitor["top"])
    except Exception:
        scrot = shutil.which("scrot")
        if scrot:
            handle, name = tempfile.mkstemp(suffix=".png")
            os.close(handle)
            subprocess.run([scrot, "-o", name], check=True, capture_output=True)
            image = Image.open(name).convert("RGB")
            image.load()
            os.remove(name)
            return image, 0, 0
        import pyautogui

        shot = pyautogui.screenshot()
        return shot.convert("RGB"), 0, 0


def capture_screen(max_width: int = 1280) -> dict[str, Any]:
    from PIL import Image

    scale = prepare_windows_dpi()
    image, origin_x, origin_y = _grab_image()
    screen_w, screen_h = image.size
    if image.width > max_width:
        height = max(1, int(image.height * (max_width / image.width)))
        image = image.resize((max_width, height), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=70)
    payload = buffer.getvalue()
    return {
        "jpeg": payload,
        "b64": base64.b64encode(payload).decode("ascii"),
        "image_width": image.width,
        "image_height": image.height,
        "screen_width": screen_w,
        "screen_height": screen_h,
        "origin_x": origin_x,
        "origin_y": origin_y,
        "dpi_scale": scale,
    }


def pointer_size() -> tuple[int, int]:
    import pyautogui

    size = pyautogui.size()
    return int(size.width), int(size.height)


def perform_action(action: dict[str, Any], frame: dict[str, Any], stop_event: threading.Event | None = None) -> str:
    if stop_event is not None and stop_event.is_set():
        return "stopped before the action"
    import pyautogui

    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    kind = str(action.get("action") or "")
    pointer_w, pointer_h = pointer_size()

    def point(x_key: str = "x", y_key: str = "y") -> tuple[int, int]:
        sx, sy = map_image_point(
            float(action.get(x_key) or 0),
            float(action.get(y_key) or 0),
            int(frame["image_width"]),
            int(frame["image_height"]),
            int(frame["screen_width"]),
            int(frame["screen_height"]),
            int(frame.get("origin_x") or 0),
            int(frame.get("origin_y") or 0),
        )
        return map_screen_to_pointer(sx, sy, int(frame["screen_width"]), int(frame["screen_height"]), pointer_w, pointer_h)

    if kind == "move":
        x, y = point()
        pyautogui.moveTo(x, y, duration=0.12)
        return f"moved to {x},{y}"
    if kind == "click":
        x, y = point()
        button = str(action.get("button") or "left")
        clicks = 2 if action.get("clicks") == 2 else 1
        pyautogui.click(x, y, clicks=clicks, button=button, duration=0.08)
        return f"{button} click at {x},{y}"
    if kind == "drag":
        x, y = point()
        x2, y2 = point("x2", "y2")
        pyautogui.moveTo(x, y, duration=0.08)
        pyautogui.dragTo(x2, y2, duration=0.25, button="left")
        return f"dragged {x},{y} to {x2},{y2}"
    if kind == "scroll":
        x, y = point()
        amount = int(action.get("dy") or action.get("amount") or -3)
        pyautogui.scroll(amount, x=x, y=y)
        return f"scrolled {amount} at {x},{y}"
    if kind == "type":
        text = str(action.get("text") or "")
        pyautogui.write(text, interval=0.02)
        return f"typed {len(text)} characters"
    if kind == "hotkey":
        keys = [str(key) for key in (action.get("keys") or [])]
        if not keys:
            return "hotkey had no keys"
        pyautogui.hotkey(*keys)
        return "hotkey " + "+".join(keys)
    if kind == "key":
        key = str(action.get("key") or "")
        pyautogui.press(key)
        return f"pressed {key}"
    if kind == "wait":
        return "waited"
    return f"unknown action {kind}"


def arm_emergency_stop(stop_event: threading.Event) -> str:
    """Ctrl+Alt+Esc. Returns a status string. Failure does not disable the Stop button."""
    global _stop_hotkey
    try:
        from pynput import keyboard

        def trip() -> None:
            stop_event.set()

        if _stop_hotkey is not None:
            return "Ctrl+Alt+Esc is armed"
        listener = keyboard.GlobalHotKeys({"<ctrl>+<alt>+<esc>": trip})
        listener.daemon = True
        listener.start()
        _stop_hotkey = listener
        return "Ctrl+Alt+Esc is armed"
    except Exception as exc:  # noqa: BLE001 — the on-screen Stop button still works
        return f"Global hotkey unavailable ({exc}). Use the Stop button."
