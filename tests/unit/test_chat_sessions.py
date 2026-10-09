from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from app.chat_sessions import ChatSessionError, ChatSessions
from app.storage import Storage


@pytest.fixture
def conversations(tmp_path):
    storage = Storage(tmp_path / "chat.sqlite3")
    storage.create_demo_session("session-a", "user-a", 100, 1000)
    storage.create_demo_session("session-b", "user-b", 100, 1000)
    return ChatSessions(storage, clock=lambda: 100)


def test_history_is_bounded_and_isolated(conversations):
    for index in range(6):
        owner, _ = conversations.acquire("session-a")
        conversations.finish("session-a", owner, f"question-{index}", f"answer-{index}")
    owner, history = conversations.acquire("session-a")
    assert history == [
        item for index in range(2, 6) for item in (f"question-{index}", f"answer-{index}")
    ]
    conversations.release("session-a", owner)
    owner, history = conversations.acquire("session-b")
    assert history == []
    conversations.release("session-b", owner)


def test_independent_connections_compete_for_same_conversation(conversations):
    other = ChatSessions(Storage(conversations.storage.path), clock=lambda: 100)
    barrier = Barrier(2)

    def acquire(store):
        barrier.wait()
        try:
            owner, _ = store.acquire("session-a")
            return owner
        except ChatSessionError as exc:
            assert exc.code == "chat_busy"
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        owners = list(pool.map(acquire, (conversations, other)))
    assert sum(owner is not None for owner in owners) == 1


def test_expired_lease_recovers_without_accepting_stale_writer(conversations):
    stale_owner, _ = conversations.acquire("session-a")
    conversations.clock = lambda: 221
    new_owner, history = conversations.acquire("session-a")
    assert history == []
    with pytest.raises(ChatSessionError, match="expirou"):
        conversations.finish("session-a", stale_owner, "stale", "stale answer")
    conversations.release("session-a", stale_owner)
    with pytest.raises(ChatSessionError, match="Aguarde"):
        conversations.acquire("session-a")
    conversations.finish("session-a", new_owner, "valid", "valid answer")
    _, history = conversations.acquire("session-a")
    assert history == ["valid", "valid answer"]


def test_expired_session_rejects_reads_and_writes(conversations):
    owner, _ = conversations.acquire("session-a")
    conversations.clock = lambda: 1000
    with pytest.raises(ChatSessionError) as expired:
        conversations.acquire("session-a")
    assert expired.value.status_code == 401
    with pytest.raises(ChatSessionError):
        conversations.finish("session-a", owner, "question", "answer")


def test_expired_session_cleanup_cascades_only_conversation_data(conversations, records):
    conversations.storage.sync_sessions(records)
    from app.reservations import ReservationService

    reservations = ReservationService(conversations.storage)
    preview = reservations.preview("S01", "user-a")
    reservations.reserve("S01", "user-a", preview["confirmation_token"], "cleanup-key-0001")
    owner, _ = conversations.acquire("session-a")
    conversations.finish("session-a", owner, "question", "answer")
    conversations.acquire("session-a")
    conversations.storage.create_demo_session("new-session", "new-user", 1000, 2000)
    with conversations.storage.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM demo_chat_messages").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM demo_chat_leases").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == 1


def test_failed_history_write_rolls_back_previous_turn(conversations):
    import sqlite3

    owner, _ = conversations.acquire("session-a")
    conversations.finish("session-a", owner, "first", "answer")
    owner, _ = conversations.acquire("session-a")
    with conversations.storage.connection() as connection:
        connection.execute(
            "CREATE TRIGGER reject_chat BEFORE INSERT ON demo_chat_messages "
            "BEGIN SELECT RAISE(ABORT, 'controlled failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conversations.finish("session-a", owner, "second", "answer")
    conversations.release("session-a", owner)
    _, history = conversations.acquire("session-a")
    assert history == ["first", "answer"]
