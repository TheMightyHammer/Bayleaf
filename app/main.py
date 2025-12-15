

"""ForagedApp: minimal FastAPI entrypoint.

This first version proves the stack works locally and in Docker.
Later we will add:
- cookbook library scanning
- indexing jobs
- search UI
- embedded EPUB/PDF reader routes
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles


APP_NAME = "Foraged"


def _get_env(name: str, default: str) -> str:
    """Small helper to keep env access consistent."""
    return os.getenv(name, default).strip() or default


def create_app() -> FastAPI:
    app = FastAPI(
        title=APP_NAME,
        version="0.1.0",
        description="Self-hosted cookbook and recipe search app.",
    )

    # Optional static folder. This allows us to add CSS/JS later without changing routes.
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/health", response_class=JSONResponse)
    def health() -> dict:
        """Simple health check for Docker / reverse proxies."""
        return {
            "status": "ok",
            "app": APP_NAME,
            "env": _get_env("FORAGED_ENV", "dev"),
        }

    @app.get("/", response_class=HTMLResponse)
    def home() -> str:
        """Temporary landing page until we build the library UI."""
        return """<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>Foraged</title>
    <style>
      body { font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif; margin: 2rem; }
      .card { max-width: 760px; border: 1px solid #e5e7eb; border-radius: 12px; padding: 1.25rem 1.5rem; }
      code { background: #f3f4f6; padding: 0.1rem 0.35rem; border-radius: 6px; }
      ul { line-height: 1.8; }
    </style>
  </head>
  <body>
    <div class=\"card\">
      <h1>Foraged</h1>
      <p>App is running. Next up: cookbook library + indexing + search.</p>
      <ul>
        <li>Health check: <code>/health</code></li>
      </ul>
    </div>
  </body>
</html>"""

    return app


app = create_app()


if __name__ == "__main__":
    # Local dev convenience. In Docker we will use the uvicorn command directly.
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=_get_env("FORAGED_HOST", "0.0.0.0"),
        port=int(_get_env("FORAGED_PORT", "8000")),
        reload=_get_env("FORAGED_RELOAD", "true").lower() in {"1", "true", "yes"},
        log_level=_get_env("FORAGED_LOG_LEVEL", "info"),
    )