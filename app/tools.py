"""Allowlisted, read-only tools exposed to the assistant."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.faq import search_faq
from app.schedule import overlaps, suggest_schedule
from app.schemas import Session


class DemoTools:
    def __init__(self, sessions: list[Session]) -> None:
        self.sessions = sessions
        self._by_id = {session.id: session for session in sessions}
        self.calls: list[str] = []

    def _record(self, name: str) -> None:
        self.calls.append(name)
        if len(self.calls) > 3:
            raise RuntimeError(
                "O limite de três chamadas de ferramenta por solicitação foi atingido."
            )

    def list_sessions(
        self, track: str | None = None, level: str | None = None, after: str | None = None
    ) -> dict[str, Any]:
        self._record("list_sessions")
        after_at = datetime.fromisoformat(after) if after else None
        result = suggest_schedule(self.sessions, track=track, level=level, after=after_at, limit=3)
        return {"sessions": result["sessions"], "reason": result["reason"]}

    def check_schedule(self, session_ids: list[str]) -> dict[str, Any]:
        self._record("check_schedule")
        if not 1 <= len(session_ids) <= 3:
            return {"valid": False, "error": "Informe de uma a três sessões."}
        unknown = sorted(set(session_ids) - self._by_id.keys())
        if unknown:
            return {"valid": False, "error": "IDs de sessão desconhecidos.", "unknown_ids": unknown}
        chosen = [self._by_id[item] for item in session_ids]
        conflicts = [
            {"first": left.id, "second": right.id}
            for index, left in enumerate(chosen)
            for right in chosen[index + 1 :]
            if overlaps(left, right)
        ]
        return {"valid": not conflicts, "conflicts": conflicts}

    def search_policy(self, question: str) -> dict[str, Any]:
        self._record("search_policy")
        result = search_faq(question)
        sources = result["sources"]
        return {
            "answer": result["answer"],
            "sources": sources if isinstance(sources, list) else [],
        }

    def adk_tools(self) -> list[Any]:
        """Return ADK-compatible function tools when the optional extra is installed."""
        return [self.list_sessions, self.check_schedule, self.search_policy]
