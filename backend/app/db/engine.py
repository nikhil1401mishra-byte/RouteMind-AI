"""Storage engine: SQLite by default, PostgreSQL + PostGIS when configured.

Both drivers expose the same small interface (`query`, `execute`,
`executescript`, `transaction`) so repositories and services never branch on
dialect. Placeholders are always written as `?`; the Postgres driver rewrites
them to `%s` before sending.

Why two drivers: SQLite ships with Python, so the control room runs on a laptop
with zero installation - which is what the SIH demo needs. PostgreSQL + PostGIS
is the production target and uses the same schema with real geometry columns.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

Row = Dict[str, Any]
Coord = Tuple[float, float]


class DatabaseError(RuntimeError):
    """Connection or query failure, carrying a message safe to show an operator."""


# ------------------------------------------------------------------ geometry
# Geometry is stored as GeoJSON text in a `geom_json` column in BOTH dialects.
# The Postgres schema adds a generated `geom` column of type geometry(...,4326)
# derived from that text, plus a GiST index. That keeps every write identical
# across drivers while still giving PostGIS real spatial indexing.

def point_geojson(lng: float, lat: float) -> str:
    return json.dumps({"type": "Point", "coordinates": [round(float(lng), 6),
                                                        round(float(lat), 6)]})


def line_geojson(coords: Sequence[Coord]) -> str:
    pts = [[round(float(c[0]), 6), round(float(c[1]), 6)] for c in coords]
    return json.dumps({"type": "LineString", "coordinates": pts})


def polygon_geojson(ring: Sequence[Coord]) -> str:
    pts = [[round(float(c[0]), 6), round(float(c[1]), 6)] for c in ring]
    if pts and pts[0] != pts[-1]:
        pts.append(pts[0])
    return json.dumps({"type": "Polygon", "coordinates": [pts]})


def bbox_of(coords: Sequence[Coord]) -> Dict[str, Optional[float]]:
    """Bounding box columns give SQLite a cheap spatial pre-filter."""
    if not coords:
        return {"min_lng": None, "min_lat": None, "max_lng": None, "max_lat": None}
    lngs = [float(c[0]) for c in coords]
    lats = [float(c[1]) for c in coords]
    return {"min_lng": min(lngs), "min_lat": min(lats),
            "max_lng": max(lngs), "max_lat": max(lats)}


def decode_geojson(text: Optional[str]) -> Optional[dict]:
    if not text:
        return None
    if isinstance(text, dict):
        return text
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


# -------------------------------------------------------------------- engines
class BaseEngine:
    dialect = "base"

    def query(self, sql: str, params: Sequence[Any] = ()) -> List[Row]:
        raise NotImplementedError

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        raise NotImplementedError

    def executescript(self, script: str) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def one(self, sql: str, params: Sequence[Any] = ()) -> Optional[Row]:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def scalar(self, sql: str, params: Sequence[Any] = ()) -> Any:
        row = self.one(sql, params)
        if not row:
            return None
        return next(iter(row.values()))


class SqliteEngine(BaseEngine):
    """Default driver. Standard library only, single file on disk."""

    dialect = "sqlite"

    def __init__(self, path: str) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        try:
            self._conn = sqlite3.connect(self.path, check_same_thread=False)
        except sqlite3.Error as exc:                       # pragma: no cover
            raise DatabaseError("Cannot open the database file " + self.path
                                + ": " + str(exc)) from exc
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")

    def query(self, sql: str, params: Sequence[Any] = ()) -> List[Row]:
        with self._lock:
            try:
                cur = self._conn.execute(sql, tuple(params))
            except sqlite3.Error as exc:
                raise DatabaseError(str(exc) + " | sql: " + sql[:200]) from exc
            rows = [dict(r) for r in cur.fetchall()]
            cur.close()
            return rows

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        with self._lock:
            try:
                cur = self._conn.execute(sql, tuple(params))
            except sqlite3.Error as exc:
                raise DatabaseError(str(exc) + " | sql: " + sql[:200]) from exc
            self._conn.commit()
            count = cur.rowcount
            cur.close()
            return count

    def executescript(self, script: str) -> None:
        with self._lock:
            try:
                self._conn.executescript(script)
            except sqlite3.Error as exc:
                raise DatabaseError("Migration failed: " + str(exc)) from exc
            self._conn.commit()

    @contextmanager
    def transaction(self):
        with self._lock:
            try:
                yield self
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class PostgresEngine(BaseEngine):
    """Production driver. Requires psycopg (v3) or psycopg2, plus PostGIS.

    NOT exercised by the bundled test suite - the development sandbox has no
    PostgreSQL server. Treat it as reviewed-but-unverified until you run
    `python -m app.db.migrate --check` against a real database.
    """

    dialect = "postgres"

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self._lock = threading.RLock()
        self._style = "psycopg3"
        try:
            import psycopg                                  # type: ignore
            from psycopg.rows import dict_row               # type: ignore
            self._conn = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
        except ImportError:
            try:
                import psycopg2                              # type: ignore
                import psycopg2.extras                       # type: ignore
            except ImportError as exc:
                raise DatabaseError(
                    "ROUTEMIND_DB=postgres was selected but no PostgreSQL driver "
                    "is installed. Install one with:  pip install 'psycopg[binary]'"
                ) from exc
            self._style = "psycopg2"
            self._psycopg2 = psycopg2
            self._extras = psycopg2.extras
            self._conn = psycopg2.connect(dsn)
            self._conn.autocommit = True
        except Exception as exc:                             # pragma: no cover
            raise DatabaseError("Cannot connect to PostgreSQL: " + str(exc)) from exc

    @staticmethod
    def _translate(sql: str) -> str:
        """Our SQL uses `?`; libpq wants `%s`. No literal `?` appears in it."""
        return sql.replace("?", "%s")

    def _cursor(self):
        if self._style == "psycopg2":
            return self._conn.cursor(cursor_factory=self._extras.RealDictCursor)
        return self._conn.cursor()

    def query(self, sql: str, params: Sequence[Any] = ()) -> List[Row]:
        with self._lock:
            try:
                with self._cursor() as cur:
                    cur.execute(self._translate(sql), tuple(params))
                    return [dict(r) for r in cur.fetchall()]
            except Exception as exc:
                raise DatabaseError(str(exc) + " | sql: " + sql[:200]) from exc

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        with self._lock:
            try:
                with self._cursor() as cur:
                    cur.execute(self._translate(sql), tuple(params))
                    return cur.rowcount
            except Exception as exc:
                raise DatabaseError(str(exc) + " | sql: " + sql[:200]) from exc

    def executescript(self, script: str) -> None:
        with self._lock:
            try:
                with self._cursor() as cur:
                    cur.execute(script)
            except Exception as exc:
                raise DatabaseError("Migration failed: " + str(exc)) from exc

    @contextmanager
    def transaction(self):
        with self._lock:
            yield self

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def create_engine(backend: str, sqlite_path: str, dsn: str = "") -> BaseEngine:
    backend = (backend or "sqlite").strip().lower()
    if backend in {"postgres", "postgresql", "postgis"}:
        if not dsn:
            raise DatabaseError(
                "ROUTEMIND_DB=postgres requires ROUTEMIND_DATABASE_URL, for example "
                "postgresql://user:pass@localhost:5432/routemind"
            )
        return PostgresEngine(dsn)
    if backend != "sqlite":
        raise DatabaseError("Unknown ROUTEMIND_DB value: " + backend
                            + " (expected 'sqlite' or 'postgres')")
    return SqliteEngine(sqlite_path)
