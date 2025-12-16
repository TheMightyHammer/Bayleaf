"""Bayleaf: FastAPI entrypoint.

Milestone: cookbook library view that lists local EPUB and PDF files.

Next milestone: SQLite-backed indexing for fast library plus recipe metadata.
"""

import os
import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.responses import FileResponse

import logging

logger = logging.getLogger("bayleaf")

from app.config import get_settings
from app.library import ALLOWED_SUFFIXES, list_cookbooks


APP_NAME = "Bayleaf"


# Helper to normalise cookbook entries (dicts or objects) to dicts for templates/indexer
def _cookbook_to_dict(b) -> dict:
    """Normalise cookbook entries (dicts or objects) to template-friendly dicts.

    Important: some implementations of `list_cookbooks()` may return objects that don't
    expose `rel_path` but do expose an absolute `path` (or `file_path`).

    We carry both `rel_path` (preferred) and `abs_path` (fallback) so callers can
    derive a stable rel_path for DB keys and URLs.
    """

    if isinstance(b, dict):
        rel_path = b.get("rel_path")
        abs_path = b.get("abs_path") or b.get("path") or b.get("file_path")
        name = b.get("name")
        suffix = b.get("suffix")
        size = b.get("size")
        mtime = b.get("mtime")
    else:
        rel_path = getattr(b, "rel_path", None)
        abs_path = getattr(b, "abs_path", None) or getattr(b, "path", None) or getattr(b, "file_path", None)
        name = getattr(b, "name", None)
        suffix = getattr(b, "suffix", None)
        size = getattr(b, "size", None)
        mtime = getattr(b, "mtime", None)

    rel_path_str = str(rel_path) if rel_path else ""
    abs_path_str = str(abs_path) if abs_path else ""

    # Prefer name if provided. Otherwise fall back to file name from rel_path/abs_path.
    if name is not None and str(name).strip():
        name_str = str(name)
    else:
        name_str = Path(rel_path_str or abs_path_str).name

    # Prefer suffix if provided. Otherwise infer from rel_path/abs_path.
    if suffix is None or str(suffix).strip() == "":
        suffix_str = Path(rel_path_str or abs_path_str).suffix
    else:
        suffix_str = str(suffix)

    return {
        "rel_path": rel_path_str,
        "abs_path": abs_path_str,
        "name": name_str,
        "suffix": suffix_str,
        "size": int(size or 0),
        "mtime": int(mtime or 0),
    }


def _get_env(name: str, default: str) -> str:
    """Read env var with backwards-compatible fallback.

    We standardise on uppercase BAYLEAF_* variables.
    We also accept legacy mixed-case Bayleaf_* variables to avoid breaking existing setups.
    """

    primary = os.getenv(name)
    if primary is not None:
        value = primary.strip()
        return value or default

    legacy_name = name.replace("BAYLEAF_", "Bayleaf_")
    legacy = os.getenv(legacy_name)
    if legacy is not None:
        value = legacy.strip()
        return value or default

    return default


def _db_path() -> str:
    return _get_env("BAYLEAF_DB_PATH", "/data/bayleaf.db")


def _connect_db() -> sqlite3.Connection:
    db_path = Path(_db_path())
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db(conn: sqlite3.Connection) -> None:
    # WAL improves read/write concurrency. Safe for our single-user MVP.
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")

    # Core tables
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS books (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          rel_path TEXT NOT NULL UNIQUE,
          file_name TEXT NOT NULL,
          file_type TEXT NOT NULL,
          file_size INTEGER NOT NULL,
          modified_mtime INTEGER NOT NULL,

          title TEXT,
          author TEXT,
          publisher TEXT,
          published_year INTEGER,
          language TEXT,
          isbn TEXT,

          cover_rel_path TEXT,
          description TEXT,

          created_at INTEGER NOT NULL DEFAULT (unixepoch()),
          updated_at INTEGER NOT NULL DEFAULT (unixepoch())
        );

        CREATE INDEX IF NOT EXISTS idx_books_file_type ON books(file_type);
        CREATE INDEX IF NOT EXISTS idx_books_author ON books(author);
        CREATE INDEX IF NOT EXISTS idx_books_title ON books(title);

        CREATE TABLE IF NOT EXISTS recipes (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          book_id INTEGER NOT NULL,

          title TEXT NOT NULL,
          ingredients_text TEXT,
          method_text TEXT,

          servings TEXT,
          prep_time_minutes INTEGER,
          cook_time_minutes INTEGER,
          total_time_minutes INTEGER,

          -- Uniqueness must be based on where the recipe came from inside the book,
          -- not the title. A single book can contain multiple "Cupcakes" recipes.
          source_type TEXT NOT NULL,
          source_key TEXT NOT NULL,

          location_type TEXT,
          location_value TEXT,

          created_at INTEGER NOT NULL DEFAULT (unixepoch()),
          updated_at INTEGER NOT NULL DEFAULT (unixepoch()),

          FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE,
          UNIQUE(book_id, source_type, source_key)
        );

        CREATE INDEX IF NOT EXISTS idx_recipes_book_id ON recipes(book_id);
        CREATE INDEX IF NOT EXISTS idx_recipes_title ON recipes(title);

        -- Tags (shared between books and recipes)
        CREATE TABLE IF NOT EXISTS tags (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS book_tags (
          book_id INTEGER NOT NULL,
          tag_id INTEGER NOT NULL,
          PRIMARY KEY (book_id, tag_id),
          FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE,
          FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_book_tags_tag_id ON book_tags(tag_id);

        CREATE TABLE IF NOT EXISTS recipe_tags (
          recipe_id INTEGER NOT NULL,
          tag_id INTEGER NOT NULL,
          PRIMARY KEY (recipe_id, tag_id),
          FOREIGN KEY(recipe_id) REFERENCES recipes(id) ON DELETE CASCADE,
          FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_recipe_tags_tag_id ON recipe_tags(tag_id);

        -- Optional but useful: track indexing runs for debugging.
        CREATE TABLE IF NOT EXISTS indexing_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          started_at INTEGER NOT NULL DEFAULT (unixepoch()),
          finished_at INTEGER,
          indexed_books INTEGER NOT NULL DEFAULT 0,
          indexed_recipes INTEGER NOT NULL DEFAULT 0,
          errors TEXT
        );
        """
    )

    # Full text search for recipes. Uses FTS5. This is built into modern SQLite.
    conn.executescript(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS recipes_fts USING fts5(
          title,
          ingredients_text,
          method_text,
          content='recipes',
          content_rowid='id'
        );

        CREATE TRIGGER IF NOT EXISTS recipes_ai AFTER INSERT ON recipes BEGIN
          INSERT INTO recipes_fts(rowid, title, ingredients_text, method_text)
          VALUES (new.id, new.title, new.ingredients_text, new.method_text);
        END;

        CREATE TRIGGER IF NOT EXISTS recipes_ad AFTER DELETE ON recipes BEGIN
          INSERT INTO recipes_fts(recipes_fts, rowid, title, ingredients_text, method_text)
          VALUES ('delete', old.id, old.title, old.ingredients_text, old.method_text);
        END;

        CREATE TRIGGER IF NOT EXISTS recipes_au AFTER UPDATE ON recipes BEGIN
          INSERT INTO recipes_fts(recipes_fts, rowid, title, ingredients_text, method_text)
          VALUES ('delete', old.id, old.title, old.ingredients_text, old.method_text);
          INSERT INTO recipes_fts(rowid, title, ingredients_text, method_text)
          VALUES (new.id, new.title, new.ingredients_text, new.method_text);
        END;
        """
    )

    conn.commit()


def _upsert_book(conn: sqlite3.Connection, *, rel_path: str, file_name: str, file_type: str, file_size: int, modified_mtime: int) -> None:
    # MVP: title/author are left as null. We'll enrich later.
    conn.execute(
        """
        INSERT INTO books (rel_path, file_name, file_type, file_size, modified_mtime, updated_at)
        VALUES (?, ?, ?, ?, ?, unixepoch())
        ON CONFLICT(rel_path) DO UPDATE SET
          file_name=excluded.file_name,
          file_type=excluded.file_type,
          file_size=excluded.file_size,
          modified_mtime=excluded.modified_mtime,
          updated_at=unixepoch();
        """,
        (rel_path, file_name, file_type, file_size, modified_mtime),
    )


def _index_books(conn: sqlite3.Connection, library_dir: Path | str) -> int:
    """Scan the library folder and sync the books table.

    This is intentionally "best effort". If a book fails to index, the app should still run.
    """

    if isinstance(library_dir, str):
        library_dir = Path(library_dir)
    if not library_dir.exists():
        return 0

    books = list_cookbooks(library_dir)
    book_dicts = [_cookbook_to_dict(b) for b in books]
    # Ensure every book has a stable rel_path. This is critical because `books.rel_path` is UNIQUE.
    # If rel_path is empty, every upsert collapses into a single row.
    root = Path(library_dir)
    for bd in book_dicts:
        if bd.get("rel_path"):
            continue

        abs_path = bd.get("abs_path") or ""
        if abs_path:
            try:
                bd["rel_path"] = str(Path(abs_path).resolve().relative_to(root.resolve()))
            except Exception:
                # If we can't safely relativise, fall back to file name (still unique-ish)
                bd["rel_path"] = Path(abs_path).name
        else:
            # Last resort. At least avoid empty string.
            bd["rel_path"] = bd.get("name") or "unknown"

    # Defensive: if a previous request left the connection mid-transaction,
    # don't try to start a nested transaction.
    if getattr(conn, "in_transaction", False):
        try:
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

    # Use the connection context manager to create a single transaction.
    # This avoids `cannot start a transaction within a transaction`.
    try:
        with conn:
            for b in book_dicts:
                rel_path = str(b["rel_path"])
                file_name = str(b.get("name") or Path(rel_path).name)
                suffix = str(b.get("suffix") or Path(rel_path).suffix).lower()
                file_type = suffix.lstrip(".")
                file_size = int(b.get("size") or 0)
                modified_mtime = int(b.get("mtime") or 0)

                _upsert_book(
                    conn,
                    rel_path=rel_path,
                    file_name=file_name,
                    file_type=file_type,
                    file_size=file_size,
                    modified_mtime=modified_mtime,
                )
    except Exception:
        # Ensure we never leave the connection in a transaction.
        try:
            conn.rollback()
        except Exception:
            pass
        raise

    return len(book_dicts)


def _query_books(conn: sqlite3.Connection, q: str | None) -> tuple[list[dict], int]:
    q = (q or "").strip()

    if q:
        like = f"%{q.lower()}%"
        rows = conn.execute(
            """
            SELECT rel_path, file_name, file_type, file_size, modified_mtime
            FROM books
            WHERE lower(file_name) LIKE ?
            ORDER BY file_name COLLATE NOCASE ASC
            """,
            (like,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT rel_path, file_name, file_type, file_size, modified_mtime
            FROM books
            ORDER BY file_name COLLATE NOCASE ASC
            """
        ).fetchall()

    # Shape results to match what templates already expect.
    books: list[dict] = []
    for r in rows:
        rel_path = str(r["rel_path"])
        name = str(r["file_name"])
        file_type = str(r["file_type"])
        suffix = f".{file_type}" if file_type else Path(rel_path).suffix
        books.append(
            {
                "rel_path": rel_path,
                "name": name,
                "suffix": suffix,
                "size": int(r["file_size"]),
                "mtime": int(r["modified_mtime"]),
            }
        )

    total = conn.execute("SELECT COUNT(*) AS c FROM books").fetchone()["c"]
    return books, int(total)


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


def _ensure_indexed(app: FastAPI) -> None:
    """Ensure DB exists and has at least one indexing pass.

    This is defensive. If startup indexing was skipped (e.g. reload timing, empty /data mount,
    first run after changing DB path), we self-heal on first request.
    """

    conn: sqlite3.Connection | None = getattr(app.state, "db", None)
    if conn is None:
        conn = _connect_db()
        _init_db(conn)
        app.state.db = conn

    # If the books table is empty, do a best-effort index.
    try:
        row = conn.execute("SELECT COUNT(*) AS c FROM books").fetchone()
        current = int(row["c"]) if row is not None else 0
    except Exception:
        # If schema is missing for any reason, recreate it.
        _init_db(conn)
        current = 0

    if current > 0:
        return

    settings = get_settings()
    try:
        index_conn = _connect_db()
        try:
            _init_db(index_conn)
            indexed = _index_books(index_conn, settings.library_dir)
        finally:
            try:
                index_conn.close()
            except Exception:
                pass
        logger.info("Indexed %s books into DB at %s", indexed, _db_path())
    except Exception as exc:
        # Do not crash the app. Record the error so we can surface it.
        logger.exception("Indexing failed: %s", exc)
        app.state.last_index_error = str(exc)


def create_app() -> FastAPI:
    app = FastAPI(
        title=APP_NAME,
        version="0.3.0",
        description="Self-hosted cookbook and recipe search app.",
    )

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    templates_dir = Path(__file__).parent / "templates"
    templates = Jinja2Templates(directory=str(templates_dir))

    @app.on_event("startup")
    def _startup() -> None:
        conn = _connect_db()
        _init_db(conn)
        app.state.db = conn

        settings = get_settings()
        logger.info("Startup. library_dir=%s db_path=%s", settings.library_dir, _db_path())

        try:
            startup_conn = _connect_db()
            try:
                _init_db(startup_conn)
                indexed = _index_books(startup_conn, settings.library_dir)
            finally:
                try:
                    startup_conn.close()
                except Exception:
                    pass
            logger.info("Startup indexing complete. indexed_books=%s", indexed)
        except Exception as exc:
            logger.exception("Startup indexing failed: %s", exc)
            app.state.last_index_error = str(exc)

    @app.get("/health", response_class=JSONResponse)
    def health() -> dict:
        conn: sqlite3.Connection | None = getattr(app.state, "db", None)
        count = None
        if conn is not None:
            try:
                count = int(conn.execute("SELECT COUNT(*) FROM books").fetchone()[0])
            except Exception:
                count = None

        return {
            "status": "ok",
            "app": APP_NAME,
            "env": _get_env("BAYLEAF_ENV", "dev"),
            "db_path": _db_path(),
            "books_indexed": count,
        }

    @app.post("/admin/reindex", response_class=JSONResponse)
    def admin_reindex() -> dict:
        """Re-run indexing.

        MVP note: This must be protected (auth or reverse proxy rules) before exposing publicly.
        """

        settings = get_settings()

        # Use a fresh connection for reindexing so we never collide with the shared
        # connection's transaction state (health checks, concurrent requests, etc.).
        conn = _connect_db()
        try:
            _init_db(conn)
            indexed = _index_books(conn, settings.library_dir)

            # Refresh the long-lived connection so subsequent requests (health/home)
            # see the newly committed data immediately.
            old: sqlite3.Connection | None = getattr(app.state, "db", None)
            try:
                if old is not None:
                    old.close()
            except Exception:
                pass

            fresh = _connect_db()
            _init_db(fresh)
            app.state.db = fresh

            return {"indexed": indexed}
        except Exception as exc:
            logger.exception("Admin reindex failed: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @app.get("/", response_class=HTMLResponse, name="home")
    def home(request: Request, q: str | None = None):
        settings = get_settings()

        _ensure_indexed(app)

        notice = ""
        if not settings.library_dir.exists():
            notice = (
                f"Library folder not found at {settings.library_dir}. "
                "Check your compose volume and BAYLEAF_LIBRARY_HOST_DIR."
            )

        conn: sqlite3.Connection = app.state.db
        books, total = _query_books(conn, q)

        if total == 0:
            # Fallback to filesystem scan so the UI never shows empty when files are mounted.
            try:
                fs_books_raw = list_cookbooks(settings.library_dir)
                fs_books = [_cookbook_to_dict(b) for b in fs_books_raw]
                # Derive rel_path for rendering links.
                root = Path(settings.library_dir)
                for bd in fs_books:
                    if bd.get("rel_path"):
                        continue
                    abs_path = bd.get("abs_path") or ""
                    if abs_path:
                        try:
                            bd["rel_path"] = str(Path(abs_path).resolve().relative_to(root.resolve()))
                        except Exception:
                            bd["rel_path"] = Path(abs_path).name
                    else:
                        bd["rel_path"] = bd.get("name") or "unknown"
                books = fs_books
                total = len(fs_books)
                if getattr(app.state, "last_index_error", ""):
                    notice = (
                        (notice + " " if notice else "")
                        + f"Indexing error: {app.state.last_index_error}"
                    )
                else:
                    notice = (
                        (notice + " " if notice else "")
                        + "DB appears empty. Showing filesystem results. Use /admin/reindex to rebuild the index."
                    )
            except Exception as exc:
                notice = (
                    (notice + " " if notice else "")
                    + f"Could not scan filesystem: {exc}"
                )

        return templates.TemplateResponse(
            "library.html",
            {
                "request": request,
                # Primary names
                "books": books,
                "total": total,
                # Backwards-compatible aliases for templates that still use older names
                "cookbooks": books,
                "count": total,
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
        host=_get_env("BAYLEAF_HOST", "0.0.0.0"),
        port=int(_get_env("BAYLEAF_PORT", "8000")),
        reload=_get_env("BAYLEAF_RELOAD", "true").lower() in {"1", "true", "yes"},
        log_level=_get_env("BAYLEAF_LOG_LEVEL", "info"),
    )
