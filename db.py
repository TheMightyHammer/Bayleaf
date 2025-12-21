import argparse
import os
import sqlite3
from pathlib import Path

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS books (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rel_path TEXT NOT NULL UNIQUE,
  file_name TEXT NOT NULL,
  file_type TEXT NOT NULL,
  file_size INTEGER NOT NULL,
  modified_mtime INTEGER NOT NULL,
  title TEXT,
  author TEXT,
  created_at INTEGER NOT NULL DEFAULT (unixepoch()),
  updated_at INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE TABLE IF NOT EXISTS recipes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  book_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  ingredients_text TEXT,
  method_text TEXT,
  location_hint TEXT,
  created_at INTEGER NOT NULL DEFAULT (unixepoch()),
  updated_at INTEGER NOT NULL DEFAULT (unixepoch()),
  FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
);

-- Full text search table for recipes. We will populate this later.
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

def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def vacuum_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.isolation_level = None
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        conn.execute("VACUUM;")
    finally:
        conn.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bayleaf database maintenance.")
    parser.add_argument(
        "command",
        choices=["vacuum"],
        help="Maintenance command to run.",
    )
    parser.add_argument(
        "--db-path",
        default=os.environ.get("BAYLEAF_DB_PATH", "/data/bayleaf.db"),
        help="Path to the SQLite database.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.command == "vacuum":
        vacuum_db(args.db_path)
        print(f"Vacuumed database at {args.db_path}")


if __name__ == "__main__":
    main()
