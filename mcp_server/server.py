"""stdio MCP server for deterministic schedule queries."""

from __future__ import annotations

import logging
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.data_validation import load_session_seed
from app.schedule import suggest_schedule
from app.schemas import Session
from app.storage import Storage

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


@lru_cache(maxsize=1)
def catalog_storage(target: str, seed_catalog: bool) -> Storage:
    storage = Storage(target)
    if seed_catalog:
        storage.seed_sessions_if_empty(load_session_seed())
    return storage


def load_sessions() -> list[Session]:
    target = os.getenv("EVENTOPS_DATABASE_URL") or str(
        Path(os.getenv("EVENTOPS_DATABASE", "var/eventops.sqlite3")).expanduser().resolve()
    )
    seed_catalog = os.getenv("EVENTOPS_SEED_CATALOG", "true").lower() in {"true", "1", "yes"}
    return [
        Session.model_validate(item)
        for item in catalog_storage(target, seed_catalog).list_sessions()
    ]


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
