"""Failure fixtures injected by evaluation code, never by public chat input."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.agent import AgentResult, ProviderError, SingleAgent
from app.agents.coordinator import COORDINATOR_PROMPT_VERSION
from app.faq import Chunk, load_chunks, search_faq
from app.mcp_client import MCPClientError, ScheduleMCPClient
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


async def exercise_mcp_process_failures(timeout_seconds: float = 0.25) -> dict[str, Any]:
    """Use real child processes to verify MCP startup timeout and abrupt exit handling."""
    outcomes: dict[str, Any] = {}
    for kind in ("delay", "crash"):
        client = ScheduleMCPClient(
            timeout_seconds=timeout_seconds,
            server_module="evals.mcp_failure_server",
            extra_env={"EVENTOPS_MCP_HARNESS": kind},
        )
        try:
            async with client:
                await client.list_tools()
            outcomes[kind] = {"handled": False, "error": None}
        except MCPClientError as exc:
            outcomes[kind] = {"handled": True, "error": str(exc)}
        finally:
            await client.close()
    return outcomes


def exercise_faq_contamination_fixture() -> dict[str, Any]:
    fixture_path = (
        Path(__file__).resolve().parent.parent
        / "tests/fixtures/adversarial/faq_poisoned_chunk.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    contaminated = Chunk(
        str(fixture["document"]),
        str(fixture["section"]),
        str(fixture["text"]),
        int(fixture["version"]),
        str(fixture["updated_at"]),
        str(fixture["status"]),
        bool(fixture["trusted"]),
    )
    poisoned_result = search_faq(str(fixture["question"]), [contaminated])
    clean_result = search_faq(str(fixture["question"]), load_chunks())
    clean_sources = clean_result.get("sources", [])
    if not isinstance(clean_sources, list):
        clean_sources = []
    metadata_propagated = bool(clean_sources) and all(
        isinstance(source, dict) and {"version", "updated_at", "status"}.issubset(source)
        for source in clean_sources
    )
    return {
        "passed": not poisoned_result.get("sources") and metadata_propagated,
        "poisoned_fixture_abstained": not bool(poisoned_result.get("sources")),
        "clean_source_cited": bool(clean_sources),
        "metadata_propagated": metadata_propagated,
        "forbidden_actions": [],
    }


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
