"""Small DB-API compatibility wrapper for the PostgreSQL storage adapter."""

from __future__ import annotations

import sqlite3
from importlib.resources import files
from typing import Any


class PostgresConnection:
    def __init__(self, connection: Any) -> None:
        self.raw = connection

    def executescript(self, script: str) -> None:
        for statement in script.split(";"):
            statement = statement.strip()
            if statement and not statement.upper().startswith("PRAGMA"):
                self.execute(statement)

    def apply_migrations(self) -> None:
        self.raw.execute("SELECT pg_advisory_lock(731905142)")
        try:
            self.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version INTEGER PRIMARY KEY CHECK(version > 0))"
            )
            rows = self.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
            migration_dir = files("app").joinpath("migrations")
            migration_files = sorted(
                (
                    int(migration.name.split("_", maxsplit=1)[0]),
                    migration,
                )
                for migration in migration_dir.iterdir()
                if migration.name.endswith(".sql")
            )
            migration_versions = sorted(
                migration_version for migration_version, _migration in migration_files
            )
            if not migration_versions:
                raise RuntimeError("Nenhuma migration PostgreSQL empacotada.")
            if migration_versions != list(range(1, migration_versions[-1] + 1)):
                raise RuntimeError("Sequência de migrations PostgreSQL contém lacunas.")
            applied_versions = {int(row["version"]) for row in rows}
            if applied_versions and max(applied_versions) > migration_versions[-1]:
                raise RuntimeError(
                    "O schema PostgreSQL é mais novo que esta aplicação "
                    f"({max(applied_versions)} > {migration_versions[-1]})."
                )
            for target_version, migration in migration_files:
                if target_version in applied_versions:
                    continue
                self.execute("BEGIN ISOLATION LEVEL SERIALIZABLE")
                try:
                    self.executescript(migration.read_text(encoding="utf-8"))
                    self.execute(
                        "INSERT INTO schema_migrations(version) VALUES(?)", (target_version,)
                    )
                    applied_versions.add(target_version)
                    self.commit()
                except Exception:
                    self.rollback()
                    raise
        finally:
            self.raw.execute("SELECT pg_advisory_unlock(731905142)")

    def execute(self, statement: str, parameters: tuple[Any, ...] = ()) -> Any:
        if statement.strip().upper().startswith("PRAGMA"):
            return None
        ignore_conflicts = "INSERT OR IGNORE INTO" in statement.upper()
        statement = statement.replace("INSERT OR IGNORE INTO", "INSERT INTO")
        if statement.strip().upper() == "BEGIN IMMEDIATE":
            statement = "BEGIN ISOLATION LEVEL SERIALIZABLE"
        statement = statement.replace("?", "%s")
        if ignore_conflicts:
            statement = statement.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
        try:
            return PostgresCursor(self.raw.execute(statement, parameters))
        except Exception as exc:
            self._translate_error(exc)
            raise

    def commit(self) -> None:
        try:
            self.raw.commit()
        except Exception as exc:
            self._translate_error(exc)
            raise

    def rollback(self) -> None:
        self.raw.rollback()

    @staticmethod
    def _translate_error(exc: Exception) -> None:
        sqlstate = getattr(exc, "sqlstate", "") or ""
        if sqlstate.startswith("23"):
            raise sqlite3.IntegrityError(str(exc)) from exc
        if sqlstate.startswith(("08", "40", "53", "57")):
            raise sqlite3.OperationalError(str(exc)) from exc


class CompatibleRow(dict[str, Any]):
    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


class PostgresCursor:
    def __init__(self, cursor: Any) -> None:
        self.raw = cursor

    def fetchone(self) -> CompatibleRow | None:
        row = self.raw.fetchone()
        return CompatibleRow(row) if row is not None else None

    def fetchall(self) -> list[CompatibleRow]:
        return [CompatibleRow(row) for row in self.raw.fetchall()]
