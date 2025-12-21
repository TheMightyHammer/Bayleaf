"""Application configuration utilities."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import os


def get_env(name: str, default: str) -> str:
    """Read an env var with backwards-compatible fallbacks."""
    candidates = [name]
    if name.startswith("BAYLEAF_"):
        suffix = name[len("BAYLEAF_") :]
        candidates.extend(
            [
                f"Bayleaf_{suffix}",
                f"FORAGED_{suffix}",
                f"Foraged_{suffix}",
            ]
        )

    for key in candidates:
        raw = os.getenv(key)
        if raw is None:
            continue
        value = raw.strip()
        return value or default

    return default


def get_db_path() -> str:
    return get_env("BAYLEAF_DB_PATH", "/data/bayleaf.db")


def get_library_dir() -> str:
    return get_env("BAYLEAF_LIBRARY_DIR", "/cookbooks")


def get_int_env(name: str, default: int) -> int:
    raw = get_env(name, str(default))
    try:
        return int(raw)
    except Exception:
        return default


def get_bool_env(name: str, default: bool) -> bool:
    raw = get_env(name, "true" if default else "false").strip().lower()
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    return default


def get_list_env(name: str) -> list[str]:
    raw = get_env(name, "").strip()
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    library_dir: Path
    env: str = "dev"
    db_path: Path | None = None
    recipe_index_limit: int = 5
    recipe_index_allowlist: tuple[str, ...] = ()
    recipe_review_enabled: bool = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    library_dir = Path(get_library_dir()).expanduser()
    env = get_env("BAYLEAF_ENV", "dev") or "dev"
    db_path = Path(get_db_path()).expanduser()
    recipe_index_limit = get_int_env("BAYLEAF_RECIPE_INDEX_LIMIT", 5)
    recipe_index_allowlist = tuple(get_list_env("BAYLEAF_RECIPE_INDEX_ALLOWLIST"))
    recipe_review_enabled = get_bool_env("BAYLEAF_RECIPE_REVIEW_ENABLED", False)
    return Settings(
        library_dir=library_dir,
        env=env,
        db_path=db_path,
        recipe_index_limit=recipe_index_limit,
        recipe_index_allowlist=recipe_index_allowlist,
        recipe_review_enabled=recipe_review_enabled,
    )
