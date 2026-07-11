"""FastAPI application factory for AI Media OS."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ai_media_os.dashboard.routes import router as dashboard_router
from ai_media_os.infrastructure.database.session import create_session_factory
from ai_media_os.infrastructure.settings import AppSettings, get_settings


def create_app(settings: AppSettings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    app = FastAPI(title=resolved.app_name)
    app.state.settings = resolved
    app.state.session_factory = create_session_factory(resolved)
    static_dir = Path(__file__).resolve().parents[1] / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    if resolved.dashboard_enabled:
        app.include_router(dashboard_router)
    return app
