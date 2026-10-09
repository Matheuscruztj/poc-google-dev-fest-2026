from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from app.reservations import ReservationError, ReservationService, token_hash
from app.storage import SCHEMA_VERSION, Storage


def test_storage_initialization_is_versioned_and_repeatable(tmp_path, records):
    path = tmp_path / "storage.sqlite3"
    storage = Storage(path)
    storage.sync_sessions(records)
    storage.create_demo_session("a" * 64, "user-a", 1, 100)

    Storage(path)

    with storage.connection() as connection:
        assert connection.execute("SELECT version FROM schema_meta").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 20
        assert len(storage.list_sessions()) == 20
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("SELECT user_id FROM demo_sessions").fetchone()[0] == "user-a"


def test_seed_only_populates_empty_database(tmp_path, records):
    storage = Storage(tmp_path / "seed.sqlite3")
    assert storage.seed_sessions_if_empty(records) is True
    with storage.connection() as connection:
        connection.execute(
            "UPDATE sessions SET title=? WHERE id='S01'", ("Título editado no banco",)
        )
    assert storage.seed_sessions_if_empty(records) is False
    first = next(item for item in storage.list_sessions() if item["id"] == "S01")
    assert first["title"] == "Título editado no banco"


def test_legacy_schema_is_upgraded_with_new_session_fields(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT NOT NULL, "
            "starts_at TEXT NOT NULL, ends_at TEXT NOT NULL, "
            "capacity INTEGER NOT NULL CHECK(capacity > 0))"
        )
        connection.execute(
            "INSERT INTO sessions VALUES('S01','Talk','2026-11-07T09:00:00-03:00',"
            "'2026-11-07T09:45:00-03:00',3)"
        )

    storage = Storage(path)

    with storage.connection() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(sessions)")}
        assert {"track", "level"} <= columns
        assert connection.execute("SELECT version FROM schema_meta").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1


def test_catalog_change_is_rejected_when_reservations_exist(tmp_path, records):
    storage = Storage(tmp_path / "catalog.sqlite3")
    storage.sync_sessions(records)
    service = ReservationService(storage)
    preview = service.preview("S01", "user-a")
    service.reserve("S01", "user-a", preview["confirmation_token"], "request-0001")
    changed = [dict(item) for item in records]
    changed[0]["capacity"] = int(changed[0]["capacity"]) + 1

    with pytest.raises(ValueError, match="catálogo mudou"):
        storage.sync_sessions(changed)

    assert storage.capacity_left("S01") == int(records[0]["capacity"]) - 1


def test_write_transaction_can_rollback_all_changes(tmp_path, records):
    storage = Storage(tmp_path / "rollback.sqlite3")
    storage.sync_sessions(records)
    with storage.connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO demo_sessions(token_hash,user_id,created_at,expires_at) VALUES(?,?,?,?)",
            ("b" * 64, "temporary-user", 1, 100),
        )
        connection.rollback()

    with storage.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM demo_sessions").fetchone()[0] == 0


def test_failed_idempotency_insert_rolls_back_reservation_and_token(tmp_path, records):
    storage = Storage(tmp_path / "atomic-reservation.sqlite3")
    storage.sync_sessions(records)
    service = ReservationService(storage)
    preview = service.preview("S01", "user-a")
    confirmation_hash = token_hash(str(preview["confirmation_token"]))
    with storage.connection() as connection:
        connection.execute(
            "CREATE TRIGGER reject_idempotency BEFORE INSERT ON idempotency "
            "BEGIN SELECT RAISE(ABORT, 'controlled failure'); END"
        )

    with pytest.raises(ReservationError, match="conflito"):
        service.reserve("S01", "user-a", str(preview["confirmation_token"]), "request-0001")

    with storage.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == 0
        row = connection.execute(
            "SELECT consumed FROM confirmations WHERE token_hash=?", (confirmation_hash,)
        ).fetchone()
    assert row["consumed"] == 0
    assert storage.capacity_left("S01") == 120


def test_future_schema_version_is_rejected(tmp_path):
    path = tmp_path / "future.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE schema_meta(version INTEGER NOT NULL)")
        connection.execute("INSERT INTO schema_meta(version) VALUES(?)", (SCHEMA_VERSION + 1,))
    with pytest.raises(RuntimeError, match="mais nova"):
        Storage(path)


def test_older_schema_meta_version_is_upgraded(tmp_path):
    path = tmp_path / "older.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE schema_meta(version INTEGER NOT NULL)")
        connection.execute("INSERT INTO schema_meta(version) VALUES(?)", (SCHEMA_VERSION - 1,))
    Storage(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT version FROM schema_meta").fetchone()[0] == SCHEMA_VERSION


def test_missing_demo_session_is_reported_without_database_lookup(tmp_path):
    storage = Storage(tmp_path / "demo.sqlite3")
    assert storage.demo_user(None, 1) is None
    assert storage.demo_session_context(None, 1) is None


def test_legacy_browser_sessions_without_expiry_are_migrated_as_expired(tmp_path):
    path = tmp_path / "legacy-cookie.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE demo_sessions(token_hash TEXT PRIMARY KEY, "
            "user_id TEXT NOT NULL, created_at REAL NOT NULL)"
        )
        connection.execute("INSERT INTO demo_sessions VALUES('old-cookie','old-user',1)")
    storage = Storage(path)
    assert storage.demo_session_context("old-cookie", 2) is None
    storage.create_demo_session("new-cookie", "new-user", 2, 100)
    assert storage.demo_session_context("new-cookie", 2) == ("new-cookie", "new-user")


def test_two_connections_compete_for_last_capacity_atomically(tmp_path, records):
    catalog = [dict(item) for item in records]
    catalog[0]["capacity"] = 1
    storage = Storage(tmp_path / "race.sqlite3")
    storage.sync_sessions(catalog)
    service = ReservationService(storage)
    previews = [service.preview("S01", f"user-{index}") for index in range(2)]
    barrier = Barrier(2)

    def reserve(index: int) -> bool:
        barrier.wait()
        try:
            service.reserve(
                "S01",
                f"user-{index}",
                str(previews[index]["confirmation_token"]),
                f"request-{index:08d}",
            )
        except ReservationError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, range(2)))

    assert sum(results) == 1
    assert storage.capacity_left("S01") == 0
