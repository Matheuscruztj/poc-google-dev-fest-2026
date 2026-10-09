"""Preview and confirmed reservation rules."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.storage import Storage


class ReservationError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code, self.code = status_code, code


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class ReservationService:
    def __init__(self, storage: Storage, ttl_seconds: int = 300, clock: Any = time.time) -> None:
        self.storage, self.ttl_seconds, self.clock = storage, ttl_seconds, clock

    def preview(self, session_id: str, user_id: str) -> dict[str, object]:
        row = self.storage.session_row(session_id)
        if row is None:
            raise ReservationError(404, "session_not_found", "Sessão não encontrada.")
        if self.storage.capacity_left(session_id) <= 0:
            raise ReservationError(409, "sold_out", "Não há vagas disponíveis nesta sessão.")
        token = secrets.token_urlsafe(32)
        with self.storage.connection() as connection:
            connection.execute(
                "INSERT INTO confirmations"
                "(token_hash,user_id,session_id,expires_at) VALUES(?,?,?,?)",
                (token_hash(token), user_id, session_id, self.clock() + self.ttl_seconds),
            )
        return {
            "session_id": session_id,
            "title": row["title"],
            "starts_at": row["starts_at"],
            "ends_at": row["ends_at"],
            "expires_in_seconds": self.ttl_seconds,
            "confirmation_token": token,
        }

    def reserve(
        self, session_id: str, user_id: str, token: str, idempotency_key: str
    ) -> dict[str, object]:
        fingerprint = hashlib.sha256(f"{user_id}\0{session_id}".encode()).hexdigest()
        try:
            with self.storage.connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                previous = connection.execute(
                    "SELECT fingerprint, receipt_id FROM idempotency WHERE user_id=? AND key=?",
                    (user_id, idempotency_key),
                ).fetchone()
                if previous:
                    if previous["fingerprint"] != fingerprint:
                        raise ReservationError(
                            409,
                            "idempotency_conflict",
                            "A chave já foi usada em outra solicitação.",
                        )
                    connection.commit()
                    return {
                        "receipt_id": previous["receipt_id"],
                        "session_id": session_id,
                        "status": "confirmed",
                        "replayed": True,
                    }
                session = connection.execute(
                    "SELECT capacity FROM sessions WHERE id=?", (session_id,)
                ).fetchone()
                if session is None:
                    raise ReservationError(404, "session_not_found", "Sessão não encontrada.")
                confirmation = connection.execute(
                    "SELECT * FROM confirmations WHERE token_hash=?", (token_hash(token),)
                ).fetchone()
                if (
                    confirmation is None
                    or confirmation["user_id"] != user_id
                    or confirmation["session_id"] != session_id
                ):
                    raise ReservationError(
                        409, "invalid_confirmation", "A confirmação é inválida para esta sessão."
                    )
                if confirmation["consumed"] or confirmation["expires_at"] <= self.clock():
                    raise ReservationError(
                        409, "expired_confirmation", "A confirmação expirou ou já foi usada."
                    )
                existing = connection.execute(
                    "SELECT receipt_id FROM reservations WHERE user_id=? AND session_id=?",
                    (user_id, session_id),
                ).fetchone()
                if existing:
                    raise ReservationError(409, "already_reserved", "Você já reservou esta sessão.")
                count = connection.execute(
                    "SELECT COUNT(*) FROM reservations WHERE session_id=?", (session_id,)
                ).fetchone()[0]
                if count >= session["capacity"]:
                    raise ReservationError(
                        409, "sold_out", "Não há vagas disponíveis nesta sessão."
                    )
                receipt = f"EVT-{uuid4().hex[:12].upper()}"
                connection.execute(
                    "INSERT INTO reservations"
                    "(receipt_id,user_id,session_id,created_at) VALUES(?,?,?,?)",
                    (receipt, user_id, session_id, self.clock()),
                )
                connection.execute(
                    "UPDATE confirmations SET consumed=1 WHERE token_hash=?", (token_hash(token),)
                )
                connection.execute(
                    "INSERT INTO idempotency(user_id,key,fingerprint,receipt_id) VALUES(?,?,?,?)",
                    (user_id, idempotency_key, fingerprint, receipt),
                )
                connection.commit()
                return {
                    "receipt_id": receipt,
                    "session_id": session_id,
                    "status": "confirmed",
                    "replayed": False,
                }
        except sqlite3.IntegrityError as exc:
            raise ReservationError(
                409, "reservation_conflict", "A reserva entrou em conflito com outra solicitação."
            ) from exc
        except sqlite3.OperationalError as exc:
            raise ReservationError(
                503, "storage_busy", "O armazenamento está ocupado; tente novamente."
            ) from exc


def seed_storage(path: Path, records: list[dict[str, object]]) -> Storage:
    storage = Storage(path)
    storage.sync_sessions(records)
    return storage
