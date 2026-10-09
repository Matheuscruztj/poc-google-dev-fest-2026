"""Failure fixtures injected by evaluation code, never by public chat input."""

from __future__ import annotations

from typing import Any

from app.agent import AgentResult, ProviderError, SingleAgent
from app.agents.coordinator import COORDINATOR_PROMPT_VERSION
from app.schemas import Session
from app.tools import DemoTools


class ControlledFailureProvider:
    def __init__(self, kind: str) -> None:
        self.kind = kind

    async def respond(
        self, message: str, tools: DemoTools, history: list[str]
    ) -> tuple[str, dict[str, int | None]]:
        del message, tools, history
        if self.kind == "tool_failure":
            raise ProviderError("Falha controlada de dependência no harness.")
        raise TimeoutError("Timeout controlado pelo harness.")


def single_agent_for_case(
    sessions: list[Session], case: dict[str, Any], default_agent: SingleAgent
) -> SingleAgent:
    if case.get("category") not in {"tool_failure", "model_failure"}:
        return default_agent
    return SingleAgent(
        sessions,
        ControlledFailureProvider(str(case["category"])),
        "offline",
        "controlled-failure-fixture",
        timeout_seconds=default_agent.timeout_seconds,
    )


def multi_failure_result(kind: str) -> AgentResult:
    failure = (
        "Falha controlada de dependência no harness."
        if kind == "tool_failure"
        else "Timeout controlado pelo harness."
    )
    return AgentResult(
        "O coordenador não conseguiu concluir. Use agenda/FAQ offline ou tente novamente.",
        [],
        [],
        None,
        "offline:multi",
        {
            "request_id": "controlled-failure-fixture",
            "mode": "offline:multi",
            "model": "offline",
            "dataset_version": COORDINATOR_PROMPT_VERSION,
            "duration_ms": 0,
            "tool_calls": 0,
            "retries": 0,
            "delegations": 0,
            "tools": [],
            "input_tokens": None,
            "output_tokens": None,
            "status": "error",
            "raw_output": None,
            "validated": False,
            "fallback": True,
            "reservation_writes": 0,
        },
        error=failure,
    )
