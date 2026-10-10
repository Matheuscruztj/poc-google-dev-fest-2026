"""Run storage contracts against a disposable local PostgreSQL container."""

from __future__ import annotations

import secrets
import shutil
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import psycopg  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.chat_sessions import ChatSessionError, ChatSessions  # noqa: E402
from app.config import Settings  # noqa: E402
from app.data_validation import load_session_seed  # noqa: E402
from app.main import create_app  # noqa: E402
from app.reservations import ReservationError, ReservationService  # noqa: E402
from app.storage import Storage  # noqa: E402


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def main() -> int:
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("Docker é necessário para make postgres-check.")
    port = free_port()
    password = secrets.token_urlsafe(24)
    database_url = f"postgresql://eventops:{password}@127.0.0.1:{port}/eventops"
    container = subprocess.run(
        [
            docker,
            "run",
            "--rm",
            "-d",
            "-e",
            "POSTGRES_USER=eventops",
            "-e",
            f"POSTGRES_PASSWORD={password}",
            "-e",
            "POSTGRES_DB=eventops",
            "-p",
            f"127.0.0.1:{port}:5432",
            "pgvector/pgvector:pg17",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    try:
        for _ in range(60):
            try:
                with psycopg.connect(database_url, connect_timeout=1) as connection:
                    connection.execute("SELECT 1")
                break
            except psycopg.OperationalError:
                time.sleep(0.25)
        else:
            raise RuntimeError("PostgreSQL temporário não ficou pronto.")

        records = load_session_seed()
        with psycopg.connect(database_url) as connection:
            connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
            connection.execute("CREATE TEMP TABLE vector_smoke (embedding vector(3))")
            connection.execute("INSERT INTO vector_smoke VALUES ('[1,0,0]'), ('[0,1,0]')")
            nearest = connection.execute(
                "SELECT embedding FROM vector_smoke "
                "ORDER BY embedding <=> '[0.9,0.1,0]'::vector LIMIT 1"
            ).fetchone()
        assert nearest is not None and str(nearest[0]) == "[1,0,0]"
        records = [dict(item, capacity=1) if item["id"] == "S01" else item for item in records]
        startup_barrier = Barrier(2)

        def initialize() -> Storage:
            startup_barrier.wait()
            return Storage(database_url)

        with ThreadPoolExecutor(max_workers=2) as pool:
            storage, _second_instance = list(pool.map(lambda _index: initialize(), range(2)))
        assert storage.seed_sessions_if_empty(records) is True
        repeat_storage = Storage(database_url)
        assert repeat_storage.seed_sessions_if_empty(records) is False
        with repeat_storage.connection() as connection:
            migration_versions = connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        assert [row["version"] for row in migration_versions] == [1, 2]
        storage.sync_sessions(records)
        storage.create_demo_session("pg-chat-session", "pg-chat-user", 100, 1000)
        chat = ChatSessions(storage, clock=lambda: 100)
        independent_chat = ChatSessions(repeat_storage, clock=lambda: 100)
        owner, history = chat.acquire("pg-chat-session")
        assert history == []
        try:
            independent_chat.acquire("pg-chat-session")
        except ChatSessionError as exc:
            assert exc.code == "chat_busy"
        else:
            raise AssertionError("Duas instâncias adquiriram a mesma conversa.")
        chat.finish("pg-chat-session", owner, "pergunta", "resposta")
        owner, history = independent_chat.acquire("pg-chat-session")
        assert history == ["pergunta", "resposta"]
        independent_chat.release("pg-chat-session", owner)
        service = ReservationService(storage)
        # Session and reservation writes remain visible across independent
        # application instances sharing the PostgreSQL database.
        settings = Settings(database_url=database_url, seed_catalog=False)
        with TestClient(create_app(settings), headers={"origin": "http://testserver"}) as client:
            assert len(client.get("/api/sessions").json()["sessions"]) == 20
            preview = client.post("/api/reservations/preview", json={"session_id": "S02"})
            payload = {
                "session_id": "S02",
                "confirmation_token": preview.json()["confirmation_token"],
                "idempotency_key": "pg-idem-key-0001",
            }
            receipt = client.post("/api/reservations", json=payload).json()
            replay = client.post("/api/reservations", json=payload).json()
            assert replay["receipt_id"] == receipt["receipt_id"] and replay["replayed"] is True
            assert client.get("/api/sessions").status_code == 200
        with repeat_storage.connection() as connection:
            persisted_receipt = connection.execute(
                "SELECT receipt_id FROM reservations WHERE user_id=? AND session_id=?",
                ("participante-demo", "S02"),
            ).fetchone()
        assert persisted_receipt is not None

        previews = [service.preview("S01", f"race-user-{index}") for index in range(2)]
        barrier = Barrier(2)

        def compete(index: int) -> str:
            barrier.wait()
            try:
                service.reserve(
                    "S01",
                    f"race-user-{index}",
                    str(previews[index]["confirmation_token"]),
                    f"pg-race-key-{index:04d}",
                )
                return "reserved"
            except ReservationError as exc:
                if exc.status_code == 503:
                    return "serialization-retry-required"
                if exc.code == "sold_out":
                    return "sold_out"
                raise

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(compete, range(2)))
        assert outcomes.count("reserved") == 1, outcomes
        assert (
            sum(outcome in {"sold_out", "serialization-retry-required"} for outcome in outcomes)
            == 1
        ), outcomes
        with storage.connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM reservations WHERE session_id=?", ("S01",)
            ).fetchone()[0]
        assert count == 1, count
        print(
            "PostgreSQL/pgvector smoke: vector extension/query, migrations, seed, "
            "chat persistence/leases, "
            "idempotency and last-seat transaction passed."
        )
        return 0
    finally:
        subprocess.run([docker, "rm", "-f", container], capture_output=True, check=False)


if __name__ == "__main__":
    raise SystemExit(main())
