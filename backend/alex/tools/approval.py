"""In-memory approval gates. The UI resolves them over the websocket or REST."""

from __future__ import annotations

import asyncio


class ApprovalService:
    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future[bool]] = {}

    def create(self, approval_id: str) -> asyncio.Future[bool]:
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._pending[approval_id] = future
        future.add_done_callback(lambda _f: self._pending.pop(approval_id, None))
        return future

    def resolve(self, approval_id: str, approved: bool) -> bool:
        future = self._pending.get(approval_id)
        if future is None or future.done():
            return False
        future.set_result(bool(approved))
        return True

    def pending_ids(self) -> list[str]:
        return [key for key, future in self._pending.items() if not future.done()]
