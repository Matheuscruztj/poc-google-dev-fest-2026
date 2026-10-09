"""Managed stdio client for the local schedule MCP server."""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import ValidationError


class MCPClientError(RuntimeError):
    """An MCP process, protocol, or tool call failed."""


class ScheduleMCPClient:
    def __init__(
        self,
        timeout_seconds: float = 3.0,
        project_root: Path | None = None,
        server_module: str = "mcp_server.server",
        database: Path | str | None = None,
        seed_catalog: bool = True,
        extra_env: dict[str, str] | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.project_root = project_root or Path(__file__).resolve().parents[1]
        self.server_module = server_module
        target = str(
            database
            or os.getenv("EVENTOPS_DATABASE_URL")
            or os.getenv("EVENTOPS_DATABASE")
            or "var/eventops.sqlite3"
        )
        if str(target).startswith(("postgresql://", "postgres://")):
            self.server_env = {"EVENTOPS_DATABASE_URL": str(target)}
        else:
            self.server_env = {"EVENTOPS_DATABASE": str(Path(target).expanduser().resolve())}
        self.server_env["EVENTOPS_SEED_CATALOG"] = "true" if seed_catalog else "false"
        self.server_env.update(extra_env or {})
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    async def start(self) -> None:
        if self._session is not None:
            return
        stack = AsyncExitStack()
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", self.server_module],
            cwd=str(self.project_root),
            env=self.server_env,
        )
        try:
            async with asyncio.timeout(self.timeout_seconds):
                read, write = await stack.enter_async_context(stdio_client(params))
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
        except Exception as exc:
            await stack.aclose()
            raise MCPClientError(
                f"Não foi possível iniciar o servidor MCP ({type(exc).__name__})."
            ) from exc
        self._stack, self._session = stack, session

    async def close(self) -> None:
        self._session = None
        if self._stack is not None:
            stack, self._stack = self._stack, None
            await stack.aclose()

    async def __aenter__(self) -> ScheduleMCPClient:
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self._call("list_tools")
        return [{"name": item.name, "inputSchema": item.inputSchema} for item in result.tools]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in {"list_sessions", "check_schedule"}:
            raise MCPClientError("Tool MCP desconhecida ou não permitida.")
        try:
            result = await self._call("call_tool", name, arguments)
        except ValidationError as exc:
            raise MCPClientError("Argumentos inválidos para a tool MCP.") from exc
        if result.isError:
            raise MCPClientError(f"A tool MCP {name} retornou erro.")
        if not result.structuredContent:
            raise MCPClientError(f"A tool MCP {name} não retornou conteúdo estruturado.")
        return dict(result.structuredContent)

    async def _call(self, method: str, *args: Any) -> Any:
        if self._session is None:
            raise MCPClientError("O cliente MCP não está iniciado.")
        try:
            operation = getattr(self._session, method)(*args)
            return await asyncio.wait_for(operation, timeout=self.timeout_seconds)
        except TimeoutError as exc:
            raise MCPClientError("A solicitação MCP excedeu o timeout.") from exc
        except MCPClientError:
            raise
        except Exception as exc:
            raise MCPClientError(f"Falha no protocolo MCP ({type(exc).__name__}).") from exc
