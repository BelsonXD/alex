"""Decide which desktop steps need another explicit approval."""

from __future__ import annotations

import re

_SENSITIVE = (
    (r"password|passcode|passwd|secret|otp|one-time code", "typing a password or secret"),
    (r"credit card|card number|cvv|cvc|expiry", "typing payment details"),
    (r"\b(buy|purchase|checkout|place order|pay now|confirm payment)\b", "a purchase"),
    (r"\b(send|reply|post|publish|submit)\b", "sending a message or submitting a form"),
    (r"\b(delete|remove|erase|format|uninstall)\b", "deleting something"),
)


def sensitivity(action: dict) -> tuple[bool, str]:
    if action.get("sensitive") is True:
        return True, "The model marked this step as sensitive."
    blob = " ".join(
        str(action.get(key) or "")
        for key in ("text", "reason", "keys", "summary", "action")
    ).lower()
    for pattern, label in _SENSITIVE:
        if re.search(pattern, blob, re.I):
            return True, f"This step looks like {label}."
    return False, ""
