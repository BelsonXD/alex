"""Example plugin: local text utilities. Drop more modules beside this file."""

from __future__ import annotations

import re


def register(registry) -> None:
    registry.tool(
        name="text_utility",
        description="Local text helper. Operations: word_count, slugify, upper, lower. No network and no approval.",
        parameters={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "description": "word_count, slugify, upper, or lower",
                },
                "text": {"type": "string", "description": "Text to transform."},
            },
            "required": ["operation", "text"],
        },
        needs_approval=False,
        handler=_handle,
    )


async def _handle(args: dict, ctx) -> object:
    from alex.tools.registry import ToolResult

    del ctx
    operation = str(args.get("operation") or "").strip().lower()
    text = str(args.get("text") or "")
    if operation == "word_count":
        count = len([part for part in text.split() if part])
        return ToolResult(True, str(count))
    if operation == "slugify":
        slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "item"
        return ToolResult(True, slug)
    if operation == "upper":
        return ToolResult(True, text.upper())
    if operation == "lower":
        return ToolResult(True, text.lower())
    return ToolResult(False, "operation must be word_count, slugify, upper, or lower.")
