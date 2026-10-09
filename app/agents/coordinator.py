"""Bounded multi-agent coordinator with shared per-request budgets."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.agent import AgentResult, ProviderError
from app.mcp_client import MCPClientError, ScheduleMCPClient
from app.resilience import CircuitBreaker, CircuitOpen, Deadline, run_with_retries
from app.schemas import Session
from app.tools import DemoTools

COORDINATOR_PROMPT_VERSION = "eventops-coordinator-v1"
SCHEDULE_AGENT_PROMPT_VERSION = "eventops-schedule-specialist-v1"
FAQ_AGENT_PROMPT_VERSION = "eventops-faq-specialist-v1"


def schedule_query(message: str, sessions: list[Session]) -> dict[str, Any]:
    normalized = message.casefold()
    track = next((item.track for item in sessions if item.track.casefold() in normalized), None)
    level = next((item.level for item in sessions if item.level.casefold() in normalized), None)
    match = re.search(r"(?:ap[oó]s|depois das?)\s*(\d{1,2})(?::(\d{2}))?", normalized)
    after = None
    if match:
        after = f"2026-11-07T{int(match.group(1)):02d}:{int(match.group(2) or 0):02d}:00-03:00"
    return {"track": track, "level": level, "after": after, "limit": 3}


@dataclass
class DelegationBudget:
    max_delegations: int = 3
    max_tool_calls: int = 3
    delegations: int = 0
    tool_calls: int = 0
    tools: list[str] = field(default_factory=list)

    def delegate(self, name: str) -> None:
        if self.delegations >= self.max_delegations:
            raise ProviderError("O limite de três delegações foi atingido.")
        self.delegations += 1
        self.tools.append(f"delegate:{name}")

    def record_tool(self, name: str) -> None:
        if self.tool_calls >= self.max_tool_calls:
            raise ProviderError("O limite global de chamadas foi atingido.")
        self.tool_calls += 1
        self.tools.append(name)


class ScheduleAgent:
    def __init__(self, sessions: list[Session], mcp: ScheduleMCPClient | None = None) -> None:
        self.sessions = sessions
        self.mcp = mcp

    async def run(self, message: str, budget: DelegationBudget) -> dict[str, Any]:
        budget.delegate("schedule_agent")
        # The specialist extracts bounded filters; MCP performs the query.
        if self.mcp is None:
            budget.record_tool("schedule.list_sessions")
            tools = DemoTools(self.sessions)
            data = tools.list_sessions(**schedule_query(message, self.sessions))
        else:
            budget.record_tool("mcp.list_sessions")
            data = await self.mcp.call_tool("list_sessions", schedule_query(message, self.sessions))
        ids = [str(item["id"]) for item in data.get("sessions", [])]
        if any(item not in {session.id for session in self.sessions} for item in ids):
            raise ProviderError("O especialista retornou IDs desconhecidos.")
        return {
            "session_ids": ids,
            "answer": (
                "Encontrei sessões no catálogo."
                if ids
                else "Não encontrei sessões compatíveis com esses filtros."
            ),
        }


class FAQAgent:
    async def run(self, message: str, budget: DelegationBudget) -> dict[str, Any]:
        budget.delegate("faq_agent")
        tools = DemoTools([])
        result = tools.search_policy(message)
        budget.record_tool("faq.search_policy")
        return result


class CoordinatorAgent:
    def __init__(
        self,
        sessions: list[Session],
        *,
        mode: str = "offline",
        model: str = "offline",
        timeout_seconds: int = 12,
        use_mcp: bool = True,
        circuit_breaker: CircuitBreaker | None = None,
        database: Path | str | None = None,
    ) -> None:
        self.sessions = sessions
        self.mode = mode
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.use_mcp = use_mcp
        self.circuit_breaker = circuit_breaker
        self.database = database

    async def ask(self, message: str, history: list[str] | None = None) -> AgentResult:
        # Routing and fallback are deterministic in offline mode. Live mode will
        # later replace only the coordinator policy while preserving specialist ACLs.
        del history
        start = time.monotonic()
        budget = DelegationBudget()
        deadline = Deadline(self.timeout_seconds)
        if self.mode in {"live", "local"}:
            provider_name = "Gemini" if self.mode == "live" else "Ollama"
            message = (
                f"A arquitetura multi com {provider_name} ainda não está configurada. "
                "Selecione agente único ou provider offline."
            )
            return AgentResult(
                message,
                [],
                [],
                None,
                "live:multi",
                {
                    "request_id": f"multi-{time.time_ns()}",
                    "mode": "live:multi",
                    "model": self.model,
                    "dataset_version": COORDINATOR_PROMPT_VERSION,
                    "duration_ms": round((time.monotonic() - start) * 1000, 2),
                    "tool_calls": 0,
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
                error=f"multi_{self.mode}_unavailable",
            )
        normalized = message.casefold()
        faq_phrases = (
            "como faço",
            "como posso",
            "qual é",
            "quais são",
            "posso cancelar",
            "tem opções",
            "confirme minha reserva",
            "duas reservas",
            "sem token",
            "token inválido",
            "ações da empresa",
            "no documento está escrito",
            "instrução do faq",
            "a faq diz",
        )
        faq_intent = any(phrase in normalized for phrase in faq_phrases)
        has_schedule_intent = any(
            word in normalized for word in ("agenda", "palestra", "sessão", "sessões", "após")
        )
        mixed_intent = has_schedule_intent and faq_intent and " e " in normalized
        is_schedule = has_schedule_intent and (not faq_intent or mixed_intent)
        is_faq = (
            not is_schedule
            or faq_intent
            or any(
                word in normalized
                for word in ("inscrição", "acessibilidade", "alimentação", "cancelar")
            )
        )
        mcp: ScheduleMCPClient | None = None
        try:
            schedule_result: dict[str, Any] = {"session_ids": [], "answer": ""}
            if is_schedule:
                if self.use_mcp:
                    if self.circuit_breaker:
                        self.circuit_breaker.allow()
                    mcp = ScheduleMCPClient(
                        timeout_seconds=min(self.timeout_seconds, 3.0),
                        database=self.database,
                        seed_catalog=self.database is None,
                    )
                    async with asyncio.timeout(deadline.remaining()):
                        await mcp.start()
                schedule_result, schedule_retries = await run_with_retries(
                    lambda: ScheduleAgent(self.sessions, mcp).run(message, budget),
                    deadline,
                    retry_if=lambda exc: isinstance(exc, (MCPClientError, TimeoutError)),
                    max_retries=2,
                )
                if self.circuit_breaker and is_schedule:
                    self.circuit_breaker.success()
            else:
                schedule_retries = 0
            faq_result: dict[str, Any] = {"answer": "", "sources": []}
            if is_faq:
                faq_result = await FAQAgent().run(message, budget)
            ids = schedule_result.get("session_ids", [])
            sources = faq_result.get("sources", [])
            known = {session.id for session in self.sessions}
            if any(item not in known for item in ids):
                raise ProviderError("O coordenador rejeitou IDs desconhecidos.")
            answer = str(
                schedule_result.get("answer")
                or faq_result.get("answer")
                or "Não encontrei evidência suficiente."
            )
            if is_schedule and is_faq and sources:
                answer = f"{schedule_result['answer']} {faq_result['answer']}"
            return AgentResult(
                answer=answer,
                session_ids=ids,
                sources=sources,
                reservation_proposal=(
                    ids[0]
                    if ids and any(word in normalized for word in ("reserv", "guardar", "vaga"))
                    else None
                ),
                mode=f"{self.mode}:multi",
                trace={
                    "request_id": f"multi-{time.time_ns()}",
                    "mode": f"{self.mode}:multi",
                    "model": self.model,
                    "dataset_version": COORDINATOR_PROMPT_VERSION,
                    "duration_ms": round((time.monotonic() - start) * 1000, 2),
                    "tool_calls": budget.tool_calls,
                    "retries": schedule_retries,
                    "delegations": budget.delegations,
                    "tools": budget.tools,
                    "input_tokens": None,
                    "output_tokens": None,
                    "status": "ok",
                    "raw_output": None,
                    "validated": True,
                    "fallback": False,
                    "reservation_writes": 0,
                    "circuit_state": (
                        self.circuit_breaker.state.value if self.circuit_breaker else "unconfigured"
                    ),
                },
            )
        except (ProviderError, MCPClientError, CircuitOpen, TimeoutError, ValueError) as exc:
            if self.circuit_breaker and isinstance(exc, (MCPClientError, TimeoutError)):
                for _ in range(max(1, budget.tool_calls)):
                    self.circuit_breaker.failure()
            partial_answer = ""
            partial_sources: list[dict[str, str]] = []
            if is_faq and budget.delegations < budget.max_delegations:
                try:
                    partial = await FAQAgent().run(message, budget)
                    partial_answer = str(partial.get("answer", ""))
                    partial_sources = partial.get("sources", [])
                except ProviderError:
                    pass
            return AgentResult(
                (
                    "Agenda indisponível; resposta parcial baseada na FAQ: " + partial_answer
                    if partial_answer
                    else (
                        "O coordenador não conseguiu concluir. "
                        "Use agenda/FAQ offline ou tente novamente."
                    )
                ),
                [],
                partial_sources,
                None,
                f"{self.mode}:multi",
                {
                    "request_id": f"multi-{time.time_ns()}",
                    "mode": f"{self.mode}:multi",
                    "model": self.model,
                    "dataset_version": COORDINATOR_PROMPT_VERSION,
                    "duration_ms": round((time.monotonic() - start) * 1000, 2),
                    "tool_calls": budget.tool_calls,
                    "retries": max(0, budget.tool_calls - 1),
                    "delegations": budget.delegations,
                    "tools": budget.tools,
                    "input_tokens": None,
                    "output_tokens": None,
                    "status": "partial" if partial_answer else "error",
                    "raw_output": None,
                    "validated": False,
                    "fallback": True,
                    "reservation_writes": 0,
                    "partial": bool(partial_answer),
                    "circuit_state": (
                        self.circuit_breaker.state.value if self.circuit_breaker else "unconfigured"
                    ),
                },
                error=str(exc),
            )
        finally:
            if mcp is not None:
                await mcp.close()
