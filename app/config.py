"""App configuration for ForagedApp.

We keep it minimal for MVP. Values are read from environment variables.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import os


@dataclass(frozen=True)
class Settings:
    library_dir: Path
    env: str = "dev"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    library_dir_str = os.getenv("FORAGED_LIBRARY_DIR", "/cookbooks").strip()
    env = os.getenv("FORAGED_ENV", "dev").strip() or "dev"
    return Settings(library_dir=Path(library_dir_str), env=env)
