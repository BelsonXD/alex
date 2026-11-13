"""ALEX application entry. Serves the API, the websocket, and the built interface."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import psutil
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from alex import __version__
from alex.api.hub import Hub
from alex.api.routes import register_routes
from alex.automations.scheduler import scheduler_loop
from alex.config import ROOT
from alex.database import init_db
from alex.plugins.loader import load_plugins
from alex.tools.approval import ApprovalService
from alex.tools.builtin import register_builtin
from alex.tools.registry import Registry

log = logging.getLogger("alex")
DIST = ROOT / "frontend" / "dist"


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db()
        psutil.cpu_percent(interval=None)
        tasks: list[asyncio.Task] = []
        if os.environ.get("ALEX_DISABLE_UPDATE_CHECK") != "1":
            tasks.append(asyncio.create_task(_update_loop(app)))
        if os.environ.get("ALEX_DISABLE_SCHEDULER") == "1":
            log.info("ALEX %s ready (scheduler off)", __version__)
            yield
            for task in tasks:
                task.cancel()
            return
        stop = asyncio.Event()
        tasks.append(asyncio.create_task(scheduler_loop(stop, app)))
        log.info("ALEX %s ready", __version__)
        yield
        stop.set()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="ALEX", version=__version__, lifespan=lifespan)
    app.state.approvals = ApprovalService()
    app.state.hub = Hub()
    app.state.started = time.time()
    app.state.computer_stop = threading.Event()
    app.state.computer_running = False
    app.state.update_status = {"version": __version__, "update_available": False, "configured": False, "detail": ""}
    registry = Registry()
    register_builtin(registry)
    app.state.registry = registry
    app.state.plugins = load_plugins(registry, ROOT / "plugins")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_routes(app)
    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    assets = DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/", include_in_schema=False, response_model=None)
    def index():
        page = DIST / "index.html"
        if page.exists():
            return FileResponse(page)
        return HTMLResponse(_missing_ui(), status_code=200)

    @app.get("/{full_path:path}", include_in_schema=False, response_model=None)
    def spa(full_path: str):
        if full_path.startswith("api") or full_path == "ws":
            raise HTTPException(404)
        if not DIST.exists():
            return HTMLResponse(_missing_ui(), status_code=200)
        candidate = (DIST / full_path).resolve()
        root = DIST.resolve()
        if candidate.is_file() and (candidate == root or root in candidate.parents):
            return FileResponse(candidate)
        index_page = DIST / "index.html"
        if index_page.exists():
            return FileResponse(index_page)
        return HTMLResponse(_missing_ui(), status_code=200)


async def _update_loop(app: FastAPI) -> None:
    from alex.updates.service import check_for_update

    while True:
        try:
            app.state.update_status = await check_for_update()
        except Exception as exc:  # noqa: BLE001
            log.info("update check failed: %s", exc)
        await asyncio.sleep(30 * 60)


def _missing_ui() -> str:
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>ALEX</title></head>
<body style="margin:0;background:#04060d;color:#d7e8f6;font-family:Segoe UI,sans-serif">
<main style="max-width:640px;margin:12vh auto;padding:24px">
<h1 style="font-weight:500;letter-spacing:0.2em">ALEX</h1>
<p>The interface has not been built yet. On Windows, double-click <strong>start.bat</strong>. It installs dependencies, builds the interface, and opens ALEX.</p>
<p>The API is already answering at <a style="color:#5de4ff" href="/api/health">/api/health</a>.</p>
</main></body></html>"""


app = create_app()
