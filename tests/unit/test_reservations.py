import pytest

from app.reservations import ReservationError, ReservationService, token_hash
from app.storage import Storage


def make_service(tmp_path, records, now=lambda: 1_800_000_000.0):
    storage = Storage(tmp_path / "reservations.sqlite3")
    storage.sync_sessions(records)
    return storage, ReservationService(storage, ttl_seconds=300, clock=now)


def test_confirmation_and_idempotent_replay(tmp_path, records):
    storage, service = make_service(tmp_path, records)
    preview = service.preview("S01", "user-a")
    first = service.reserve("S01", "user-a", preview["confirmation_token"], "request-0001")
    replay = service.reserve("S01", "user-a", "now-expired-token-does-not-matter", "request-0001")
    assert replay["receipt_id"] == first["receipt_id"]
    assert replay["replayed"] is True
    assert storage.capacity_left("S01") == 119


def test_preview_stores_confirmation_hash_not_raw_token(tmp_path, records):
    storage, service = make_service(tmp_path, records)
    preview = service.preview("S01", "user-a")
    with storage.connection() as connection:
        row = connection.execute("SELECT token_hash FROM confirmations").fetchone()
    assert row["token_hash"] == token_hash(str(preview["confirmation_token"]))
    assert row["token_hash"] != preview["confirmation_token"]


def test_unknown_session_cannot_create_preview(tmp_path, records):
    _, service = make_service(tmp_path, records)
    with pytest.raises(ReservationError, match="Sessão não encontrada") as error:
        service.preview("UNKNOWN", "user-a")
    assert error.value.status_code == 404


def test_preview_rejects_exhausted_capacity(tmp_path, records):
    catalog = [dict(item) for item in records]
    catalog[0]["capacity"] = 1
    storage = Storage(tmp_path / "sold-out.sqlite3")
    storage.sync_sessions(catalog)
    service = ReservationService(storage)
    preview = service.preview("S01", "user-a")
    service.reserve("S01", "user-a", preview["confirmation_token"], "request-0001")
    with pytest.raises(ReservationError, match="Não há vagas") as error:
        service.preview("S01", "user-b")
    assert error.value.status_code == 409


def test_second_idempotency_key_cannot_duplicate_user_session(tmp_path, records):
    _, service = make_service(tmp_path, records)
    preview = service.preview("S01", "user-a")
    service.reserve("S01", "user-a", preview["confirmation_token"], "request-0001")
    second_preview = service.preview("S01", "user-a")
    with pytest.raises(ReservationError, match="já reservou") as error:
        service.reserve("S01", "user-a", second_preview["confirmation_token"], "request-0002")
    assert error.value.code == "already_reserved"


def test_key_reuse_for_other_session_conflicts(tmp_path, records):
    _, service = make_service(tmp_path, records)
    preview = service.preview("S01", "user-a")
    service.reserve("S01", "user-a", preview["confirmation_token"], "request-0001")
    with pytest.raises(ReservationError, match="outra solicitação"):
        service.reserve("S02", "user-a", "irrelevant", "request-0001")


def test_confirmation_is_bound_to_user_and_session(tmp_path, records):
    _, service = make_service(tmp_path, records)
    preview = service.preview("S01", "user-a")
    with pytest.raises(ReservationError, match="inválida"):
        service.reserve("S02", "user-a", preview["confirmation_token"], "request-0002")


def test_confirmation_cannot_be_used_by_another_user(tmp_path, records):
    _, service = make_service(tmp_path, records)
    preview = service.preview("S01", "user-a")
    with pytest.raises(ReservationError, match="inválida"):
        service.reserve("S01", "user-b", preview["confirmation_token"], "request-0003")


def test_expired_confirmation_cannot_write(tmp_path, records):
    now = [1_800_000_000.0]
    storage = Storage(tmp_path / "reservations.sqlite3")
    storage.sync_sessions(records)
    service = ReservationService(storage, 5, lambda: now[0])
    preview = service.preview("S01", "user-a")
    now[0] += 6
    with pytest.raises(ReservationError, match="expirou"):
        service.reserve("S01", "user-a", preview["confirmation_token"], "request-0003")
    assert storage.capacity_left("S01") == 120


def test_session_isolation_uses_stored_hash_only(tmp_path, records):
    storage, _ = make_service(tmp_path, records)
    storage.create_demo_session(token_hash("secret-cookie"), "user-a", 1.0, 10.0)
    assert storage.demo_user(token_hash("secret-cookie"), 5.0) == "user-a"
    assert storage.demo_user(token_hash("secret-cookie"), 11.0) is None
    assert storage.demo_user("secret-cookie", 5.0) is None
