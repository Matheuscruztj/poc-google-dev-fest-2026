"""Deterministic session filtering, conflict checks and schedule selection."""

from __future__ import annotations

import re
from datetime import datetime
from itertools import combinations
from typing import Any

from app.schemas import Session


def sessions_from_records(records: list[dict[str, Any]]) -> list[Session]:
    sessions = [Session.model_validate(record) for record in records]
    if len(sessions) != 20 or len({item.id for item in sessions}) != len(sessions):
        raise ValueError("O catálogo precisa conter exatamente 20 sessões com IDs únicos.")
    if any(re.fullmatch(r"S\d{2}", item.id) is None for item in sessions):
        raise ValueError("IDs de sessão devem seguir o formato estável S01–S99.")
    dates = {item.starts_at.date() for item in sessions}
    offsets = {item.starts_at.utcoffset() for item in sessions}
    if len(dates) != 1 or len(offsets) != 1:
        raise ValueError("As sessões do catálogo precisam compartilhar data e fuso do evento.")
    return sessions


def overlaps(left: Session, right: Session) -> bool:
    return left.starts_at < right.ends_at and right.starts_at < left.ends_at


def suggest_schedule(
    sessions: list[Session],
    *,
    track: str | None = None,
    level: str | None = None,
    after: datetime | None = None,
    limit: int = 3,
) -> dict[str, Any]:
    if not 1 <= limit <= 3:
        raise ValueError("O limite deve estar entre 1 e 3.")
    candidates = [
        item
        for item in sessions
        if (track is None or item.track.casefold() == track.casefold())
        and (level is None or item.level.casefold() == level.casefold())
        and (after is None or item.starts_at >= after)
    ]
    chosen: tuple[Session, ...] = ()
    for size in range(min(limit, len(candidates)), 0, -1):
        valid = [
            group
            for group in combinations(candidates, size)
            if all(not overlaps(a, b) for a, b in combinations(group, 2))
        ]
        if valid:
            chosen = min(
                valid, key=lambda group: tuple(sorted((item.starts_at, item.id) for item in group))
            )
            break
    ordered = sorted(chosen, key=lambda item: (item.starts_at, item.id))
    reason = None
    if len(ordered) < limit:
        reason = "Há menos opções compatíveis com esses filtros e sem conflito de horário."
    return {"sessions": [item.model_dump(mode="json") for item in ordered], "reason": reason}
