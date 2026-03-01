"""FastAPI application factory."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from nasvetlo.db import init_db


def create_app() -> FastAPI:
    init_db()

    app = FastAPI(title="На Светло", docs_url=None, redoc_url=None)

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    from nasvetlo.web.routes.public import router as public_router
    from nasvetlo.web.routes.dashboard import router as dashboard_router

    app.include_router(public_router)
    app.include_router(dashboard_router, prefix="/dashboard")

    return app
