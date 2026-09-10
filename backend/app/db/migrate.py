"""Migration runner.

Applies numbered `.sql` files from `migrations/<dialect>/` in filename order and
records each one in `schema_migrations`, so re-running is a no-op. Run directly:

    python -m app.db.migrate            # apply pending migrations
    python -m app.db.migrate --status   # list applied / pending
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import List, Tuple

from .engine import BaseEngine, DatabaseError

MIGRATIONS_ROOT = Path(__file__).resolve().parent / "migrations"

BOOTSTRAP = (
    "CREATE TABLE IF NOT EXISTS schema_migrations ("
    "  version TEXT PRIMARY KEY,"
    "  applied_at DOUBLE PRECISION NOT NULL"
    ")"
)


def _bootstrap_sql(dialect: str) -> str:
    if dialect == "sqlite":
        return BOOTSTRAP.replace("DOUBLE PRECISION", "REAL")
    return BOOTSTRAP


def migration_files(dialect: str) -> List[Path]:
    folder = MIGRATIONS_ROOT / dialect
    if not folder.is_dir():
        raise DatabaseError("No migrations directory for dialect " + dialect)
    return sorted(p for p in folder.glob("*.sql") if p.is_file())


def applied_versions(engine: BaseEngine) -> List[str]:
    engine.execute(_bootstrap_sql(engine.dialect))
    rows = engine.query("SELECT version FROM schema_migrations ORDER BY version")
    return [r["version"] for r in rows]


def _split_statements(sql: str) -> List[str]:
    """Split a script into single statements.

    psycopg refuses multi-statement SQL in one execute call, so the PostgreSQL
    path sends statements one at a time. Our migration files contain no
    semicolons inside string literals or dollar-quoted bodies, which keeps this
    split safe and the runner simple.
    """
    out: List[str] = []
    for chunk in sql.split(";"):
        stmt = "\n".join(
            line for line in chunk.splitlines()
            if not line.strip().startswith("--")
        ).strip()
        if stmt:
            out.append(stmt)
    return out


def migrate(engine: BaseEngine, verbose: bool = False) -> List[str]:
    """Apply every pending migration. Returns the versions applied this run."""
    done = set(applied_versions(engine))
    newly: List[str] = []

    for path in migration_files(engine.dialect):
        version = path.stem
        if version in done:
            continue
        sql = path.read_text(encoding="utf-8")
        if engine.dialect == "postgres":
            for statement in _split_statements(sql):
                engine.execute(statement)
        else:
            engine.executescript(sql)
        engine.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (version, time.time()),
        )
        newly.append(version)
        if verbose:
            print("  applied " + version)

    return newly


def status(engine: BaseEngine) -> Tuple[List[str], List[str]]:
    done = set(applied_versions(engine))
    pending = [p.stem for p in migration_files(engine.dialect) if p.stem not in done]
    return sorted(done), pending


def _main(argv: List[str]) -> int:                          # pragma: no cover
    from . import get_engine

    engine = get_engine()
    if "--status" in argv:
        done, pending = status(engine)
        print("dialect: " + engine.dialect)
        print("applied: " + (", ".join(done) or "none"))
        print("pending: " + (", ".join(pending) or "none"))
        return 0
    applied = migrate(engine, verbose=True)
    print("dialect: " + engine.dialect)
    print("migrations applied: "
          + (", ".join(applied) if applied else "none (already up to date)"))
    return 0


if __name__ == "__main__":                                  # pragma: no cover
    sys.exit(_main(sys.argv[1:]))
