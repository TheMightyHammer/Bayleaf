from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re
import sqlite3
from typing import Iterable

ALLOWED_SUFFIXES = {".epub", ".pdf"}

@dataclass(frozen=True)
class BookFile:
    rel_path: str
    file_name: str
    file_type: str
    file_size: int
    modified_mtime: int
    title: str | None
    author: str | None

def guess_title_author(file_name: str) -> tuple[str | None, str | None]:
    base = Path(file_name).stem
    # Common pattern: "Author - Title" or "Title - Author"
    parts = [p.strip() for p in re.split(r"\s-\s", base) if p.strip()]
    if len(parts) >= 2:
        # Heuristic: if first part looks like a person name, treat as author.
        if " " in parts[0] and parts[0][0].isalpha():
            return (" - ".join(parts[1:]), parts[0])
        return (parts[0], " - ".join(parts[1:]))
    return (base, None)

def iter_book_files(library_dir: str) -> Iterable[BookFile]:
    root = Path(library_dir).expanduser().resolve()
    if not root.exists():
        return

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            continue

        stat = path.stat()
        rel_path = str(path.relative_to(root))
        title, author = guess_title_author(path.name)

        yield BookFile(
            rel_path=rel_path,
            file_name=path.name,
            file_type=path.suffix.lower().lstrip("."),
            file_size=stat.st_size,
            modified_mtime=int(stat.st_mtime),
            title=title,
            author=author,
        )

def upsert_books(conn: sqlite3.Connection, books: Iterable[BookFile]) -> int:
    count = 0
    conn.execute("BEGIN")
    for b in books:
        conn.execute(
            """
            INSERT INTO books (rel_path, file_name, file_type, file_size, modified_mtime, title, author, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, unixepoch())
            ON CONFLICT(rel_path) DO UPDATE SET
              file_name=excluded.file_name,
              file_type=excluded.file_type,
              file_size=excluded.file_size,
              modified_mtime=excluded.modified_mtime,
              title=COALESCE(books.title, excluded.title),
              author=COALESCE(books.author, excluded.author),
              updated_at=unixepoch()
            """,
            (b.rel_path, b.file_name, b.file_type, b.file_size, b.modified_mtime, b.title, b.author),
        )
        count += 1
    conn.commit()
    return count

def purge_missing_books(conn: sqlite3.Connection, library_dir: str) -> int:
    root = Path(library_dir).expanduser().resolve()
    rows = conn.execute("SELECT id, rel_path FROM books").fetchall()
    missing_ids: list[int] = []
    for r in rows:
        full_path = root / r["rel_path"]
        if not full_path.exists():
            missing_ids.append(int(r["id"]))

    if not missing_ids:
        return 0

    conn.execute("BEGIN")
    conn.executemany("DELETE FROM books WHERE id = ?", [(i,) for i in missing_ids])
    conn.commit()
    return len(missing_ids)