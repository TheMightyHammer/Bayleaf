"""Library utilities for finding and filtering cookbooks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional


ALLOWED_SUFFIXES = {".pdf", ".epub"}


@dataclass(frozen=True)
class Cookbook:
    title: str
    path: Path
    suffix: str


def list_cookbooks(root: Path | str) -> List[Cookbook]:
    """Recursively list cookbooks under root."""
    root = Path(root)
    if not root.exists():
        return []
    items: List[Cookbook] = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in ALLOWED_SUFFIXES:
            items.append(Cookbook(title=p.stem, path=p, suffix=p.suffix.lower()))
    items.sort(key=lambda c: c.title.lower())
    return items


def filter_cookbooks(cookbooks: Iterable[Cookbook], q: Optional[str]) -> List[Cookbook]:
    """Filter cookbooks by a simple case-insensitive substring match on title."""
    if not q:
        return list(cookbooks)
    qn = q.strip().lower()
    return [c for c in cookbooks if qn in c.title.lower()]
