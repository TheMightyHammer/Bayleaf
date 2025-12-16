"""ForagedApp: FastAPI entrypoint.

Milestone: cookbook library view that lists local EPUB and PDF files.
"""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.responses import FileResponse

from app.config import get_settings
from app.library import ALLOWED_SUFFIXES, filter_cookbooks, list_cookbooks

APP_NAME = "Bayleaf"


def _get_env(name: str, default: str) -> str:
    return os.getenv(name, default).strip() or default


def _safe_resolve(root: Path, rel_path: str) -> Path:
    root_resolved = root.resolve()
    candidate = (root_resolved / rel_path).resolve()

    try:
        candidate.relative_to(root_resolved)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc

    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Not found")

    if candidate.suffix.lower() not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=404, detail="Not found")

    return candidate


def create_app() -> FastAPI:
    app = FastAPI(
        title=APP_NAME,
        version="0.2.0",
        description="Self-hosted cookbook and recipe search app.",
    )

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    templates_dir = Path(__file__).parent / "templates"
    templates = Jinja2Templates(directory=str(templates_dir))

    @app.get("/health", response_class=JSONResponse)
    def health() -> dict:
        return {"status": "ok", "app": APP_NAME, "env": _get_env("Bayleaf_ENV", "dev")}

    @app.get("/", response_class=HTMLResponse, name="home")
    def home(request: Request, q: str | None = None):
        settings = get_settings()
        books = list_cookbooks(settings.library_dir)
        total = len(books)
        books = filter_cookbooks(books, (q or "").strip())

        notice = ""
        if not settings.library_dir.exists():
            notice = (
                f"Library folder not found at {settings.library_dir}. "
                "Check your compose volume and Bayleaf_LIBRARY_HOST_DIR."
            )

        return templates.TemplateResponse(
            "library.html",
            {
                "request": request,
                "books": books,
                "total": total,
                "q": (q or "").strip(),
                "library_dir": str(settings.library_dir),
                "notice": notice,
            },
        )

    @app.get("/read/{rel_path:path}", response_class=HTMLResponse, name="read_book")
    def read_book(request: Request, rel_path: str):
        settings = get_settings()
        file_path = _safe_resolve(settings.library_dir, rel_path)
        title = file_path.stem
        file_type = file_path.suffix.lower().lstrip(".")
        return templates.TemplateResponse(
            "read.html",
            {"request": request, "title": title, "rel_path": rel_path, "file_type": file_type},
        )

    @app.get("/file/{rel_path:path}", name="file")
    def file(rel_path: str):
        settings = get_settings()
        file_path = _safe_resolve(settings.library_dir, rel_path)

        media_type = "application/octet-stream"
        if file_path.suffix.lower() == ".pdf":
            media_type = "application/pdf"
        if file_path.suffix.lower() == ".epub":
            media_type = "application/epub+zip"

        return FileResponse(path=str(file_path), media_type=media_type, filename=file_path.name)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=_get_env("Bayleaf_HOST", "0.0.0.0"),
        port=int(_get_env("Bayleaf_PORT", "8000")),
        reload=_get_env("Bayleaf_RELOAD", "true").lower() in {"1", "true", "yes"},
        log_level=_get_env("Bayleaf_LOG_LEVEL", "info"),
    )
