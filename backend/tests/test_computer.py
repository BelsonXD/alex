import os
import threading

import pytest

from alex.computer_use.desktop import map_image_point, map_screen_to_pointer
from alex.computer_use.loop import parse_action, run_computer_task
from alex.computer_use.safety import sensitivity


def test_live_screenshot_when_a_display_is_available():
    if not os.environ.get("DISPLAY"):
        pytest.skip("no display")
    from alex.computer_use.desktop import capture_screen

    frame = capture_screen()
    assert frame["jpeg"][:2] == b"\xff\xd8"
    assert frame["screen_width"] > 0
    assert frame["image_width"] <= 1280


def test_dpi_mapping_scales_screenshot_pixels_onto_the_screen():
    # A 1280-wide preview of a 2560-wide 150% desktop.
    x, y = map_image_point(100, 50, 1280, 720, 2560, 1440)
    assert (x, y) == (200, 100)
    pointer = map_screen_to_pointer(200, 100, 2560, 1440, 2560, 1440)
    assert pointer == (200, 100)


def test_sensitive_steps_are_password_purchase_send_and_delete():
    assert sensitivity({"action": "type", "text": "hunter2", "reason": "enter the password"})[0]
    assert sensitivity({"action": "click", "reason": "pay now"})[0]
    assert sensitivity({"action": "click", "reason": "open notepad"})[0] is False
    assert sensitivity({"action": "hotkey", "keys": ["ctrl", "enter"], "reason": "send the email"})[0]
    assert sensitivity({"action": "type", "text": "hello", "reason": "search"})[0] is False
    assert sensitivity({"action": "click", "reason": "delete the file", "sensitive": True})[0]


def test_parse_action_accepts_fenced_json():
    action = parse_action('Sure\n```json\n{"action":"click","x":1,"y":2,"reason":"ok"}\n```')
    assert action["action"] == "click"


@pytest.mark.asyncio
async def test_computer_loop_asks_before_start_and_before_a_password():
    events = []
    performed = []
    approvals = []

    async def on_event(event):
        events.append(event)

    async def approval(request):
        approvals.append(request.tool)
        return request.tool == "computer_use"

    class Provider:
        def is_configured(self):
            return True

        def status_detail(self):
            return "ok"

    script = [
        {"action": "click", "x": 10, "y": 10, "reason": "focus"},
        {"action": "type", "text": "secret", "reason": "enter the password"},
        {"action": "done", "summary": "finished"},
    ]

    async def decide(provider, model, goal, history, frame):
        del provider, model, goal, history, frame
        return script.pop(0)

    def capture():
        return {
            "b64": "aW1n",
            "image_width": 100,
            "image_height": 100,
            "screen_width": 100,
            "screen_height": 100,
            "origin_x": 0,
            "origin_y": 0,
            "dpi_scale": 1.5,
        }

    def act(action, frame, stop_event):
        del frame, stop_event
        performed.append(action["action"])
        return "ok"

    await run_computer_task(
        goal="log in",
        on_event=on_event,
        approval=approval,
        stop_event=threading.Event(),
        enabled=True,
        max_steps=5,
        provider_name="openai",
        model="gpt-4o",
        provider=Provider(),
        capture=capture,
        act=act,
        decide=decide,
    )
    assert approvals == ["computer_use", "computer_use_step"]
    assert performed == ["click"]
    assert any(event.get("type") == "computer_done" for event in events)


@pytest.mark.asyncio
async def test_stop_flag_ends_the_loop_before_another_action():
    stop = threading.Event()
    stop.set()
    events = []

    async def on_event(event):
        events.append(event)

    async def approval(request):
        del request
        return True

    class Provider:
        def is_configured(self):
            return True

        def status_detail(self):
            return "ok"

    await run_computer_task(
        goal="look",
        on_event=on_event,
        approval=approval,
        stop_event=stop,
        enabled=True,
        max_steps=3,
        provider_name="openai",
        model="gpt-4o",
        provider=Provider(),
        capture=lambda: {"b64": "a", "image_width": 1, "image_height": 1, "screen_width": 1, "screen_height": 1},
        act=lambda action, frame, stop_event: "should-not-run",
        decide=lambda *args, **kwargs: {"action": "click", "x": 0, "y": 0},
    )
    assert events[-1]["summary"] == "Stopped."
