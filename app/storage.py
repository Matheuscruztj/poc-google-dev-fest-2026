"""SQLite persistence for the synthetic catalog and reservation runtime."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.postgres_compat import PostgresConnection

SCHEMA_VERSION = 2

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, track TEXT NOT NULL DEFAULT '',
  level TEXT NOT NULL DEFAULT '', starts_at TEXT NOT NULL,
  ends_at TEXT NOT NULL, capacity INTEGER NOT NULL CHECK(capacity > 0)
);
CREATE TABLE IF NOT EXISTS schema_meta (version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS catalog_state (
  singleton INTEGER PRIMARY KEY CHECK(singleton = 1), content_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS demo_sessions (
  token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, created_at REAL NOT NULL,
  expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS confirmations (
  token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL,
  session_id TEXT NOT NULL REFERENCES sessions(id),
  expires_at REAL NOT NULL, consumed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS reservations (
  receipt_id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
  session_id TEXT NOT NULL REFERENCES sessions(id),
  created_at REAL NOT NULL, UNIQUE(user_id, session_id)
);
CREATE TABLE IF NOT EXISTS idempotency (
  user_id TEXT NOT NULL, key TEXT NOT NULL, fingerprint TEXT NOT NULL,
  receipt_id TEXT NOT NULL REFERENCES reservations(receipt_id), PRIMARY KEY(user_id, key)
);
CREATE INDEX IF NOT EXISTS reservations_by_session ON reservations(session_id);
"""


class Storage:
    def __init__(self, path: Path | str) -> None:
        self.database_url = (
            path
            if isinstance(path, str) and path.startswith(("postgresql://", "postgres://"))
            else None
        )
        self.path = Path("/tmp/eventops-cloud-sql") if self.database_url else Path(path)
        if not self.database_url:  # pragma: no branch - PostgreSQL is covered by postgres-check.
            self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            if self.database_url:  # pragma: no branch - PostgreSQL is covered by postgres-check.
                connection.apply_migrations()
            else:
                connection.executescript(SCHEMA)
            # PostgreSQL's schema is managed by its versioned migrations.
            if not self.database_url:  # pragma: no branch
                columns = {
                    str(row["name"]) for row in connection.execute("PRAGMA table_info(sessions)")
                }
                if "track" not in columns:
                    connection.execute(
                        "ALTER TABLE sessions ADD COLUMN track TEXT NOT NULL DEFAULT ''"
                    )
                if "level" not in columns:
                    connection.execute(
                        "ALTER TABLE sessions ADD COLUMN level TEXT NOT NULL DEFAULT ''"
                    )
            version_row = connection.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()
            if version_row is None:
                connection.execute("INSERT INTO schema_meta(version) VALUES(?)", (SCHEMA_VERSION,))
            elif int(version_row["version"]) > SCHEMA_VERSION:
                raise RuntimeError(
                    "A versão do banco é mais nova que a suportada por esta aplicação."
                )
            elif int(version_row["version"]) < SCHEMA_VERSION:
                connection.execute("UPDATE schema_meta SET version=?", (SCHEMA_VERSION,))

    @contextmanager
    def connection(self) -> Iterator[Any]:
        if self.database_url:  # pragma: no branch - PostgreSQL is covered by postgres-check.
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise RuntimeError("Instale psycopg para usar EVENTOPS_DATABASE_URL.") from exc
            raw = psycopg.connect(
                self.database_url,
                autocommit=True,
                row_factory=dict_row,
                options="-c default_transaction_isolation=serializable",
            )
            postgres_connection = PostgresConnection(raw)
            try:
                yield postgres_connection
            finally:
                raw.close()
            return
        sqlite_connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        sqlite_connection.row_factory = sqlite3.Row
        sqlite_connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield sqlite_connection
        finally:
            sqlite_connection.close()

    def sync_sessions(self, records: list[dict[str, object]]) -> None:
        canonical = json.dumps(records, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                previous = connection.execute(
                    "SELECT content_hash FROM catalog_state WHERE singleton=1"
                ).fetchone()
                reservations = int(
                    connection.execute("SELECT COUNT(*) FROM reservations").fetchone()[0]
                )
                if previous and previous["content_hash"] != content_hash and reservations:
                    raise ValueError(
                        "O catálogo mudou enquanto há reservas; migre os dados explicitamente."
                    )
                for item in records:
                    connection.execute(
                        "INSERT INTO sessions(id,title,track,level,starts_at,ends_at,capacity) "
                        "VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                        "title=excluded.title, track=excluded.track, level=excluded.level, "
                        "starts_at=excluded.starts_at, ends_at=excluded.ends_at, "
                        "capacity=excluded.capacity",
                        (
                            item["id"],
                            item["title"],
                            item["track"],
                            item["level"],
                            item["starts_at"],
                            item["ends_at"],
                            item["capacity"],
                        ),
                    )
                connection.execute(
                    "INSERT INTO catalog_state(singleton,content_hash) VALUES(1,?) "
                    "ON CONFLICT(singleton) DO UPDATE SET content_hash=excluded.content_hash",
                    (content_hash,),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def seed_sessions_if_empty(self, records: list[dict[str, object]]) -> bool:
        """Seed a blank database once; return whether the seed was applied."""
        with self.connection() as connection:
            count = int(connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
        if count:
            return False
        self.sync_sessions(records)
        return True

    def list_sessions(self) -> list[dict[str, object]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT id,title,track,level,starts_at,ends_at,capacity "
                "FROM sessions ORDER BY starts_at,id"
            ).fetchall()
            return [dict(row) for row in rows]

    def session_row(self, session_id: str) -> Any | None:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            return row

    def create_demo_session(
        self, token_hash: str, user_id: str, now: float, expires_at: float
    ) -> None:
        with self.connection() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO demo_sessions"
                "(token_hash,user_id,created_at,expires_at) VALUES(?,?,?,?)",
                (token_hash, user_id, now, expires_at),
            )

    def demo_user(self, token_hash: str | None, now: float) -> str | None:
        if not token_hash:
            return None
        with self.connection() as connection:
            row = connection.execute(
                "SELECT user_id FROM demo_sessions WHERE token_hash=? AND expires_at>?",
                (token_hash, now),
            ).fetchone()
            return str(row["user_id"]) if row else None

    def demo_session_context(self, token_hash: str | None, now: float) -> tuple[str, str] | None:
        if not token_hash:
            return None
        with self.connection() as connection:
            row = connection.execute(
                "SELECT token_hash,user_id FROM demo_sessions WHERE token_hash=? AND expires_at>?",
                (token_hash, now),
            ).fetchone()
            return (str(row["token_hash"]), str(row["user_id"])) if row else None

    def capacity_left(self, session_id: str) -> int:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT s.capacity - COUNT(r.receipt_id) AS remaining FROM sessions s "
                "LEFT JOIN reservations r ON r.session_id=s.id WHERE s.id=? GROUP BY s.id",
                (session_id,),
            ).fetchone()
            return int(row["remaining"]) if row else 0
