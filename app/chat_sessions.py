"""Bounded conversation history and exclusive expiring leases in the database."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

from app.storage import Storage


class ChatSessionError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code, self.code = status_code, code


class ChatSessions:
    # Longer than the longest configured provider deadline (65 s). A crashed
    # process releases its lease through expiry; stale owners cannot save turns.
    LEASE_SECONDS = 120

    def __init__(self, storage: Storage, clock: Callable[[], float] = time.time) -> None:
        self.storage, self.clock = storage, clock

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        try:
            with self.storage.connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    yield connection
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except sqlite3.OperationalError as exc:
            raise ChatSessionError(
                503, "storage_busy", "O armazenamento está ocupado; tente novamente."
            ) from exc

    def acquire(self, session_hash: str) -> tuple[str, list[str]]:
        owner = str(uuid4())
        now = self.clock()
        with self._transaction() as connection:
            session = connection.execute(
                "SELECT user_id FROM demo_sessions WHERE token_hash=? AND expires_at>?",
                (session_hash, now),
            ).fetchone()
            if session is None:
                raise ChatSessionError(401, "session_expired", "A sessão expirou. Tente novamente.")
            connection.execute(
                "INSERT INTO demo_chat_leases(demo_session_hash,owner,expires_at) VALUES(?,?,?) "
                "ON CONFLICT(demo_session_hash) DO UPDATE SET "
                "owner=excluded.owner, expires_at=excluded.expires_at "
                "WHERE demo_chat_leases.expires_at<=?",
                (session_hash, owner, now + self.LEASE_SECONDS, now),
            )
            lease = connection.execute(
                "SELECT owner FROM demo_chat_leases WHERE demo_session_hash=?", (session_hash,)
            ).fetchone()
            if lease["owner"] != owner:
                raise ChatSessionError(
                    409, "chat_busy", "Aguarde a resposta atual antes de enviar outra mensagem."
                )
            history = connection.execute(
                "SELECT content FROM demo_chat_messages WHERE demo_session_hash=? "
                "ORDER BY position",
                (session_hash,),
            ).fetchall()
            return owner, [str(row["content"]) for row in history]

    def finish(self, session_hash: str, owner: str, message: str, answer: str) -> None:
        now = self.clock()
        with self._transaction() as connection:
            lease = connection.execute(
                "SELECT l.owner FROM demo_chat_leases l JOIN demo_sessions s "
                "ON s.token_hash=l.demo_session_hash "
                "WHERE l.demo_session_hash=? AND l.owner=? AND l.expires_at>? AND s.expires_at>?",
                (session_hash, owner, now, now),
            ).fetchone()
            if lease is None:
                raise ChatSessionError(
                    409, "chat_lease_expired", "A solicitação expirou. Envie a mensagem novamente."
                )
            rows = connection.execute(
                "SELECT content FROM demo_chat_messages WHERE demo_session_hash=? "
                "ORDER BY position",
                (session_hash,),
            ).fetchall()
            history = [str(row["content"]) for row in rows] + [message, answer]
            connection.execute(
                "DELETE FROM demo_chat_messages WHERE demo_session_hash=?", (session_hash,)
            )
            for position, content in enumerate(history[-8:]):
                connection.execute(
                    "INSERT INTO demo_chat_messages(demo_session_hash,position,content) "
                    "VALUES(?,?,?)",
                    (session_hash, position, content),
                )
            connection.execute(
                "DELETE FROM demo_chat_leases WHERE demo_session_hash=? AND owner=?",
                (session_hash, owner),
            )

    def release(self, session_hash: str, owner: str) -> None:
        with self._transaction() as connection:
            connection.execute(
                "DELETE FROM demo_chat_leases WHERE demo_session_hash=? AND owner=?",
                (session_hash, owner),
            )
