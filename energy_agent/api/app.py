"""Standalone tool-service application factory."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .routes import router
from .chat import WEB_DIR, page_router, router as chat_router
from .student_analysis import router as student_analysis_router
from .focused_analysis import router as focused_analysis_router


def create_app(data_dir: str | Path | None = None) -> FastAPI:
    application = FastAPI(title="Energy Equipment Tools", version="1.0.0")
    application.state.energy_data_dir = data_dir
    application.include_router(router)
    application.include_router(chat_router)
    application.include_router(student_analysis_router)
    application.include_router(focused_analysis_router)
    application.include_router(page_router)
    application.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    @application.get("/", include_in_schema=False)
    def home():
        return RedirectResponse("/chat")
    return application


app = create_app()
