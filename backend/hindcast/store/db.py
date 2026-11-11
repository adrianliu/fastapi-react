"""SQLite connection and numbered migrations (spec 7).

The database is one file, `~/.hindcast/hindcast.db`, in WAL mode. Override it with `HINDCAST_DB`
(or `APP_DB`, kept for the repo's test conventions). Every caller opens its own short-lived
connection with `get_db()`; the job worker thread does the same.

Migrations are `migrations/NNN_name.sql`, applied in numeric order and recorded in
`schema_migrations`. Number ranges per area (never edit another area's range):
  001-099 foundation, 100-199 adapters/import, 200-249 episodes/labeling/groups,
  250-299 task candidates, 300-349 fixes, 350-399 bench.
"""

import os
import re
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from hindcast.config import hindcast_home

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_MIGRATION_RE = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")
_migrate_lock = threading.Lock()
_migrated: set[Path] = set()


def db_path() -> Path:
    for env in ("HINDCAST_DB", "APP_DB"):
        value = os.environ.get(env)
        if value:
            return Path(value).expanduser()
    return hindcast_home() / "hindcast.db"


def utc_now() -> str:
    """UTC timestamp in ISO 8601 with a `Z` suffix, the format used in every TEXT time column."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open a connection with WAL, foreign keys and `sqlite3.Row` rows. Migrates on first use."""
    target = path or db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    resolved = target.resolve()
    if resolved not in _migrated:
        with _migrate_lock:
            if resolved not in _migrated:
                migrate(conn)
                _migrated.add(resolved)
    return conn


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    """A connection whose `with` block is one transaction: commit on success, rollback on error."""
    conn = connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def migration_files() -> list[tuple[int, Path]]:
    found: list[tuple[int, Path]] = []
    for path in MIGRATIONS_DIR.iterdir():
        m = _MIGRATION_RE.match(path.name)
        if m:
            found.append((int(m.group(1)), path))
    found.sort()
    numbers = [n for n, _ in found]
    if len(numbers) != len(set(numbers)):
        raise RuntimeError(f"duplicate migration numbers in {MIGRATIONS_DIR}")
    return found


def migrate(conn: sqlite3.Connection) -> list[int]:
    """Apply pending migrations. Returns the numbers applied."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations"
        " (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
    )
    done = {int(r[0]) for r in conn.execute("SELECT version FROM schema_migrations")}
    applied: list[int] = []
    for number, path in migration_files():
        if number in done:
            continue
        script = path.read_text()
        # executescript commits first; wrap the migration and its record in one transaction.
        try:
            conn.executescript(
                "BEGIN;\n"
                + script
                + "\nINSERT INTO schema_migrations (version, name, applied_at) VALUES"
                + f" ({number}, '{path.name}', '{utc_now()}');\nCOMMIT;"
            )
        except sqlite3.Error:
            if conn.in_transaction:
                conn.rollback()
            raise
        applied.append(number)
    return applied
