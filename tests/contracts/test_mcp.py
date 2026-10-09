from __future__ import annotations

import asyncio

import pytest

from app.mcp_client import MCPClientError, ScheduleMCPClient
from app.schedule import suggest_schedule
from app.schemas import Session
from app.storage import Storage

pytestmark = pytest.mark.usefixtures("mcp_database")


@pytest.mark.anyio
async def test_stdio_mcp_discovery_and_catalog_contract(records):
    sessions = [Session.model_validate(item) for item in records]
    async with ScheduleMCPClient(timeout_seconds=10) as client:
        tools = await client.list_tools()
        assert {item["name"] for item in tools} == {"list_sessions", "check_schedule"}
        result = await client.call_tool("list_sessions", {"track": "IA", "limit": 3})
        expected = suggest_schedule(sessions, track="IA", limit=3)
        assert [item["id"] for item in result["sessions"]] == [
            item["id"] for item in expected["sessions"]
        ]


@pytest.mark.anyio
async def test_stdio_mcp_rejects_unknown_ids_and_invalid_payload():
    async with ScheduleMCPClient(timeout_seconds=10) as client:
        unknown = await client.call_tool("check_schedule", {"session_ids": ["S999"]})
        assert unknown["valid"] is False
        assert unknown["unknown_ids"] == ["S999"]
        with pytest.raises(MCPClientError, match="não retornou conteúdo|retornou erro"):
            await client.call_tool("list_sessions", {"limit": 9})


@pytest.mark.anyio
async def test_stdio_mcp_client_rejects_unlisted_tool():
    async with ScheduleMCPClient(timeout_seconds=10) as client:
        with pytest.raises(MCPClientError, match="não permitida"):
            await client.call_tool("reserve_seat", {})


@pytest.mark.anyio
async def test_stdio_mcp_call_cancellation_still_closes_transport():
    client = ScheduleMCPClient(timeout_seconds=10)
    await client.start()
    pending = asyncio.create_task(client.call_tool("list_sessions", {"limit": 3}))
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    await client.close()
    assert client._session is None
    assert client._stack is None


@pytest.mark.anyio
async def test_stdio_mcp_missing_process_fails_without_leaking_process(tmp_path):
    client = ScheduleMCPClient(
        timeout_seconds=2,
        project_root=tmp_path,
        server_module="mcp_server.module_that_does_not_exist",
    )
    with pytest.raises(MCPClientError):
        await client.start()
    await client.close()


def test_stdio_mcp_schema_rejects_extra_fields():
    from pydantic import ValidationError

    from mcp_server.server import ListSessionsInput

    with pytest.raises(ValidationError):
        ListSessionsInput.model_validate({"limit": 1, "user_id": "admin"})


@pytest.mark.anyio
async def test_mcp_uses_database_changes_even_after_process_start(mcp_database):
    storage = Storage(mcp_database)
    async with ScheduleMCPClient(database=mcp_database, seed_catalog=False) as client:
        before = await client.call_tool("list_sessions", {"track": "IA", "limit": 3})
        assert before["sessions"]
        with storage.connection() as connection:
            connection.execute("UPDATE sessions SET track='Banco' WHERE track='IA'")
        after = await client.call_tool("list_sessions", {"track": "IA", "limit": 3})
        persisted = await client.call_tool("list_sessions", {"track": "Banco", "limit": 3})
        assert after["sessions"] == []
        assert persisted["sessions"]
        assert all(item["track"] == "Banco" for item in persisted["sessions"])


@pytest.mark.anyio
async def test_mcp_does_not_reseed_empty_database_when_disabled(tmp_path):
    database = tmp_path / "empty.sqlite3"
    async with ScheduleMCPClient(database=database, seed_catalog=False) as client:
        result = await client.call_tool("list_sessions", {"limit": 3})
    assert result["sessions"] == []
