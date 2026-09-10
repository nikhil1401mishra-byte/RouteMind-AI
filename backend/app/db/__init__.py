"""Database package: engine singleton, migrations, repositories.

Usage from services:

    from .db import repo
    incidents = repo("incidents")
    incidents.insert({...})
"""

from __future__ import annotations

from typing import Optional

from .. import config
from .engine import (BaseEngine, DatabaseError, bbox_of, create_engine,
                     decode_geojson, line_geojson, point_geojson,
                     polygon_geojson)
from .migrate import migrate, status
from .repositories import (DATA_CLASSES, Repository, TABLES, ValidationError,
                           new_id, now, repository)

_engine: Optional[BaseEngine] = None
_ready = False


def get_engine() -> BaseEngine:
    """Return the process-wide engine, creating it on first use."""
    global _engine
    if _engine is None:
        _engine = create_engine(config.DB_BACKEND, str(config.SQLITE_PATH),
                                config.DATABASE_URL)
    return _engine


def init(force: bool = False) -> BaseEngine:
    """Open the database and apply pending migrations. Safe to call repeatedly."""
    global _ready
    engine = get_engine()
    if force or not _ready:
        migrate(engine)
        _ready = True
    return engine


def repo(table: str) -> Repository:
    return repository(init(), table)


def reset(path: Optional[str] = None) -> BaseEngine:
    """Drop the current connection and open a fresh one. Used by tests."""
    global _engine, _ready
    if _engine is not None:
        try:
            _engine.close()
        except Exception:
            pass
    _engine = None
    _ready = False
    if path is not None:
        config.SQLITE_PATH = path
    return init(force=True)


__all__ = [
    "BaseEngine", "DatabaseError", "Repository", "TABLES", "ValidationError",
    "DATA_CLASSES", "bbox_of", "decode_geojson", "get_engine", "init",
    "line_geojson", "migrate", "new_id", "now", "point_geojson",
    "polygon_geojson", "repo", "reset", "status",
]
