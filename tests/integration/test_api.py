import asyncio

import pytest
from starlette.requests import Request

from app.config import Settings
from app.main import create_app
from app.reservations import token_hash
from app.schemas import ChatRequest


def test_health_and_catalog(client):
    assert client.get("/health").json() == {
        "status": "ok",
        "mode": "offline",
        "agent_mode": "offline",
        "model": "none",
    }
    result = client.get("/api/sessions")
    assert result.status_code == 200
    assert len(result.json()["sessions"]) == 20


def test_catalog_reads_current_sqlite_rows(client):
    storage = client.app.state.storage
    with storage.connection() as connection:
        connection.execute("UPDATE sessions SET title='Título vindo do banco' WHERE id='S01'")
    result = client.get("/api/sessions")
    session = next(item for item in result.json()["sessions"] if item["id"] == "S01")
    assert session["title"] == "Título vindo do banco"


def test_schedule_and_faq_contracts(client):
    schedule = client.post("/api/schedule", json={"track": "IA", "limit": 3})
    assert schedule.status_code == 200
    assert len(schedule.json()["sessions"]) <= 3
    faq = client.post("/api/faq", json={"question": "Quais são as opções de acessibilidade?"})
    assert faq.status_code == 200
    assert faq.json()["sources"]
    assert "acessibilidade.md" in {source["document"] for source in faq.json()["sources"]}


def test_preview_and_confirmation_return_single_receipt(client):
    preview = client.post("/api/reservations/preview", json={"session_id": "S01"})
    assert preview.status_code == 200
    assert "httponly" in preview.headers["set-cookie"].lower()
    assert "samesite=lax" in preview.headers["set-cookie"].lower()
    assert "max-age=86400" in preview.headers["set-cookie"].lower()
    payload = {
        "session_id": "S01",
        "confirmation_token": preview.json()["confirmation_token"],
        "idempotency_key": "api-request-0001",
    }
    first = client.post("/api/reservations", json=payload)
    replay = client.post("/api/reservations", json=payload)
    assert first.status_code == 200
    assert replay.json()["receipt_id"] == first.json()["receipt_id"]


def test_client_cannot_choose_identity(client):
    response = client.post(
        "/api/reservations/preview", json={"session_id": "S01", "user_id": "admin"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


def test_http_errors_use_sanitized_contract_and_request_id(client):
    invalid = client.post("/api/faq", json={"question": "x", "api_key": "secret-value"})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "invalid_request"
    assert "secret-value" not in invalid.text
    missing = client.get("/api/does-not-exist")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert missing.json()["error"]["request_id"] == missing.headers["x-request-id"]


def test_confirmation_cannot_cross_browser_sessions(client):
    preview = client.post("/api/reservations/preview", json={"session_id": "S01"})
    other_browser = client.__class__(client.app, headers={"origin": "http://testserver"})
    payload = {
        "session_id": "S01",
        "confirmation_token": preview.json()["confirmation_token"],
        "idempotency_key": "cross-browser-0001",
    }
    rejected = other_browser.post("/api/reservations", json=payload)
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "invalid_confirmation"
    accepted = client.post("/api/reservations", json=payload)
    assert accepted.status_code == 200


def test_unknown_session_and_invalid_confirmation_statuses(client):
    unknown = client.post("/api/reservations/preview", json={"session_id": "UNKNOWN"})
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "session_not_found"
    invalid = client.post(
        "/api/reservations",
        json={
            "session_id": "S01",
            "confirmation_token": "invalid-token",
            "idempotency_key": "invalid-confirm-0001",
        },
    )
    assert invalid.status_code == 409
    assert invalid.json()["error"]["code"] == "invalid_confirmation"


def test_mutation_rejects_foreign_origin(client):
    response = client.post(
        "/api/reservations/preview",
        json={"session_id": "S01"},
        headers={"origin": "https://malicious.example"},
    )
    assert response.status_code == 403


def test_mutation_rejects_missing_origin(client):
    response = client.post(
        "/api/reservations/preview",
        json={"session_id": "S01"},
        headers={"origin": ""},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "origin_not_allowed"


def test_browser_sessions_receive_independent_demo_identities(client):
    first = client.post("/api/reservations/preview", json={"session_id": "S01"})
    second_browser = client.__class__(client.app, headers={"origin": "http://testserver"})
    second = second_browser.post("/api/reservations/preview", json={"session_id": "S01"})
    with client.app.state.storage.connection() as connection:
        users = connection.execute("SELECT user_id FROM demo_sessions ORDER BY user_id").fetchall()
    assert first.status_code == second.status_code == 200
    assert len({row["user_id"] for row in users}) == 2


def test_chat_offline_proposes_reservation_without_writing(client):
    response = client.post("/api/chat", json={"message": "Quero reservar palestra de IA após 14h"})
    assert response.status_code == 200
    result = response.json()
    assert result["mode"] == "offline"
    assert result["reservation_proposal"] in result["session_ids"]
    assert result["trace"]["fallback"] is False
    with client.app.state.storage.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == 0


def test_public_chat_cannot_activate_failure_harness(client):
    response = client.post("/api/chat", json={"message": "SIMULATE_TIMEOUT: agenda de IA"})
    assert response.status_code == 200
    assert response.json()["error"] is None
    assert response.json()["trace"]["fallback"] is False


def test_chat_can_select_multi_architecture_offline(client):
    response = client.post(
        "/api/chat",
        json={"message": "Palestras de IA após 14h", "architecture": "multi"},
    )
    assert response.status_code == 200
    assert response.json()["mode"] == "offline:multi"
    assert response.json()["trace"]["delegations"] == 1
    assert response.json()["trace"]["tools"][-1] == "mcp.list_sessions"


def test_chat_rejects_unknown_architecture(client):
    response = client.post(
        "/api/chat", json={"message": "Palestras de IA", "architecture": "agent-swarm"}
    )
    assert response.status_code == 422


def test_chat_rejects_extra_identity_fields(client):
    response = client.post(
        "/api/chat", json={"message": "Quais trilhas existem?", "user_id": "admin"}
    )
    assert response.status_code == 422


def test_chat_history_is_partitioned_by_browser_cookie(client):
    first = client.post("/api/chat", json={"message": "Quais trilhas existem?"})
    other = client.__class__(client.app, headers={"origin": "http://testserver"})
    second = other.post("/api/chat", json={"message": "Quais trilhas existem?"})
    assert first.status_code == second.status_code == 200
    assert client.cookies.get("eventops_demo") != other.cookies.get("eventops_demo")
    with client.app.state.storage.connection() as connection:
        count = connection.execute(
            "SELECT COUNT(DISTINCT demo_session_hash) FROM demo_chat_messages"
        ).fetchone()[0]
    assert count == 2


def test_chat_history_survives_application_restart(client, monkeypatch):
    message = "Quais trilhas existem?"
    first = client.post("/api/chat", json={"message": message}).json()
    cookie = client.cookies.get("eventops_demo")
    histories = []

    class RecordingAgent:
        async def ask(self, message, history):
            from app.agent import AgentResult

            histories.append(history)
            return AgentResult("Resposta seguinte", [], [], None, "offline", {})

    monkeypatch.setattr("app.main.make_agent", lambda *args, **kwargs: RecordingAgent())
    restarted = create_app(Settings(database=client.app.state.settings.database))
    with client.__class__(restarted, headers={"origin": "http://testserver"}) as other:
        other.cookies.set("eventops_demo", cookie)
        response = other.post("/api/chat", json={"message": "Qual é o fuso?"})
        assert response.status_code == 200
        assert "set-cookie" not in response.headers
    assert histories == [[message, first["answer"]]]


def test_parallel_chat_for_same_browser_returns_busy(client):
    client.post("/api/chat", json={"message": "Quais trilhas existem?"})
    session_hash = token_hash(client.cookies.get("eventops_demo"))
    owner, _ = client.app.state.chat_sessions.acquire(session_hash)
    try:
        response = client.post("/api/chat", json={"message": "Qual é o fuso?"})
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "chat_busy"
    finally:
        client.app.state.chat_sessions.release(session_hash, owner)
    assert client.post("/api/chat", json={"message": "Qual é o fuso?"}).status_code == 200


def test_unexpected_agent_error_releases_chat_lease(client, monkeypatch):
    class BrokenAgent:
        async def ask(self, message, history):
            raise RuntimeError("controlled failure")

    monkeypatch.setattr("app.main.make_agent", lambda *args, **kwargs: BrokenAgent())
    with client.__class__(
        client.app, headers={"origin": "http://testserver"}, raise_server_exceptions=False
    ) as browser:
        assert browser.post("/api/chat", json={"message": "Qual é o fuso?"}).status_code == 500
    with client.app.state.storage.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM demo_chat_leases").fetchone()[0] == 0


@pytest.mark.anyio
async def test_cancelled_chat_releases_lease(client, monkeypatch):
    class CancelledAgent:
        async def ask(self, message, history):
            raise asyncio.CancelledError

    monkeypatch.setattr("app.main.make_agent", lambda *args, **kwargs: CancelledAgent())
    request = Request(
        {
            "type": "http",
            "scheme": "http",
            "server": ("testserver", 80),
            "path": "/api/chat",
            "headers": [(b"host", b"testserver"), (b"origin", b"http://testserver")],
        }
    )
    endpoint = next(route.endpoint for route in client.app.routes if route.path == "/api/chat")
    with pytest.raises(asyncio.CancelledError):
        await endpoint(ChatRequest(message="Qual é o fuso?"), request)
    with client.app.state.storage.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM demo_chat_leases").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM demo_chat_messages").fetchone()[0] == 0


def test_api_and_multi_share_persisted_catalog(client):
    with client.app.state.storage.connection() as connection:
        connection.execute("UPDATE sessions SET track='Banco' WHERE track='IA'")
    for architecture in ("single", "multi"):
        response = client.post(
            "/api/chat", json={"message": "Palestras de Banco", "architecture": architecture}
        )
        assert response.status_code == 200
        result = response.json()
        assert result["error"] is None
        assert result["session_ids"]
        catalog = client.get("/api/sessions", params={"track": "Banco"}).json()["sessions"]
        assert set(result["session_ids"]) <= {item["id"] for item in catalog}


def test_frontend_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "DEMO OFFLINE" in response.text


def test_openapi_documents_w2_contracts(client):
    schema = client.get("/openapi.json").json()
    assert "/api/schedule" in schema["paths"]
    assert "/api/faq" in schema["paths"]
    assert "/api/reservations/preview" in schema["paths"]
    assert "ReservationRequest" in schema["components"]["schemas"]
