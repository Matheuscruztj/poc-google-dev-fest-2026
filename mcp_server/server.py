"""stdio MCP server for deterministic schedule queries."""

from __future__ import annotations

import json
import logging
import sys
from importlib.resources import files
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.schedule import suggest_schedule
from app.schemas import Session

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s %(message)s")
LOGGER = logging.getLogger("eventops.mcp")
mcp = FastMCP("eventops-schedule")


class ListSessionsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    track: str | None = Field(default=None, max_length=80)
    level: str | None = Field(default=None, max_length=40)
    after: str | None = Field(default=None, max_length=64)
    limit: int = Field(default=3, ge=1, le=3)


class CheckScheduleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_ids: list[str] = Field(min_length=1, max_length=3)


def load_sessions() -> list[Session]:
    # Reading through the package resource API works from wheel installs too.
    resource = files("app").joinpath("data", "sessions.json")
    records = json.loads(resource.read_text(encoding="utf-8"))
    sessions = [Session.model_validate(item) for item in records]
    if len(sessions) != 20 or len({item.id for item in sessions}) != 20:
        raise ValueError("O catálogo empacotado deve conter 20 sessões com IDs únicos.")
    return sessions


def list_sessions_impl(payload: dict[str, Any]) -> dict[str, Any]:
    request = ListSessionsInput.model_validate(payload)
    sessions = load_sessions()
    from datetime import datetime

    after = datetime.fromisoformat(request.after) if request.after else None
    return suggest_schedule(
        sessions,
        track=request.track,
        level=request.level,
        after=after,
        limit=request.limit,
    )


def check_schedule_impl(payload: dict[str, Any]) -> dict[str, Any]:
    request = CheckScheduleInput.model_validate(payload)
    from app.schedule import overlaps

    sessions = {item.id: item for item in load_sessions()}
    unknown = sorted(set(request.session_ids) - sessions.keys())
    if unknown:
        return {"valid": False, "error": "IDs de sessão desconhecidos.", "unknown_ids": unknown}
    chosen = [sessions[item] for item in request.session_ids]
    conflicts = [
        {"first": left.id, "second": right.id}
        for index, left in enumerate(chosen)
        for right in chosen[index + 1 :]
        if overlaps(left, right)
    ]
    return {"valid": not conflicts, "conflicts": conflicts}


@mcp.tool()
def list_sessions(
    track: str | None = None,
    level: str | None = None,
    after: str | None = None,
    limit: int = 3,
) -> dict[str, Any]:
    """Lista até três sessões sem conflito; horários ISO-8601 com fuso explícito."""
    return list_sessions_impl({"track": track, "level": level, "after": after, "limit": limit})


@mcp.tool()
def check_schedule(session_ids: list[str]) -> dict[str, Any]:
    """Verifica IDs conhecidos e conflitos entre sessões selecionadas."""
    return check_schedule_impl({"session_ids": session_ids})


def main() -> None:
    try:
        load_sessions()
        mcp.run(transport="stdio")
    except (OSError, ValueError, ValidationError) as exc:
        LOGGER.error("Falha ao iniciar servidor MCP: %s", exc)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
