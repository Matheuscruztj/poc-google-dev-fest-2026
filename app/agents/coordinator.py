"""Bounded multi-agent coordinator with shared per-request budgets."""

from __future__ import annotations

import asyncio
import json
import re
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from app.agent import AgentResult, ProviderError
from app.mcp_client import MCPClientError, ScheduleMCPClient
from app.resilience import CircuitBreaker, CircuitOpen, Deadline, run_with_retries
from app.schemas import Session
from app.tools import DemoTools

COORDINATOR_PROMPT_VERSION = "eventops-coordinator-v1"
SCHEDULE_AGENT_PROMPT_VERSION = "eventops-schedule-specialist-v1"
FAQ_AGENT_PROMPT_VERSION = "eventops-faq-specialist-v1"


def schedule_query(message: str, sessions: list[Session]) -> dict[str, Any]:
    normalized = unicodedata.normalize("NFKD", message.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = re.sub(r"\bdev\b", "desenvolvimento", normalized)

    def normalize_track(value: str) -> str:
        return unicodedata.normalize("NFKD", value.casefold()).encode("ascii", "ignore").decode()

    track = next(
        (
            item.track
            for item in sessions
            if re.search(rf"\b{re.escape(normalize_track(item.track))}\b", normalized)
        ),
        None,
    )
    level_aliases = {
        "iniciante": r"\biniciant(?:e|es)\b",
        "intermediario": r"\bintermediari(?:o|a|os|as)\b",
        "avancado": r"\bavancad(?:o|a|os|as)\b",
    }
    level = next(
        (
            item.level
            for item in sessions
            if re.search(level_aliases[item.level.casefold()], normalized)
        ),
        None,
    )
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
            query = schedule_query(message, self.sessions)
            query.pop("limit", None)
            data = tools.list_sessions(**query)
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
        result = await asyncio.to_thread(tools.search_policy, message)
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
        api_key: str | None = None,
        ollama_base_url: str = "http://127.0.0.1:11434",
        vertex_ai: bool = False,
        google_project: str | None = None,
        google_location: str = "us-central1",
    ) -> None:
        self.sessions = sessions
        self.mode = mode
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.use_mcp = use_mcp
        self.circuit_breaker = circuit_breaker
        self.database = database
        self.api_key = api_key
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.vertex_ai = vertex_ai
        self.google_project = google_project
        self.google_location = google_location

    async def _route_with_model(self, message: str) -> tuple[bool, bool]:
        """Ask the configured model which bounded local specialists should run."""
        instruction = (
            "Classifique a solicitação para um assistente de evento. Responda somente JSON válido, "
            "sem markdown e sem comentários, exatamente neste formato: "
            '{"schedule":true,"faq":false}. '
            "Use somente booleanos JSON. schedule=true para agenda/palestras; "
            "faq=true para regras, informações e políticas. Para pedidos ambíguos, "
            "marque faq=true. "
            "Não responda ao usuário nem invente dados. Pergunta: " + message[:2000]
        )
        if self.mode == "live":
            if not self.api_key and not self.vertex_ai:
                raise ProviderError("GOOGLE_API_KEY não está configurada para o coordenador.")

            def invoke_google() -> str:
                from google import genai
                from google.genai import types

                client = (
                    genai.Client(
                        vertexai=True,
                        api_key=self.api_key,
                        project=self.google_project,
                        location=self.google_location,
                    )
                    if self.vertex_ai
                    else genai.Client(api_key=self.api_key)
                )
                response = client.models.generate_content(
                    model=self.model,
                    contents=instruction,
                    config=types.GenerateContentConfig(
                        temperature=0,
                        max_output_tokens=512,
                    ),
                )
                parsed = getattr(response, "parsed", None)
                if isinstance(parsed, dict):
                    return json.dumps(parsed, ensure_ascii=False)
                # Prefer the text convenience property, but some Vertex response
                # candidates expose structured JSON only through content parts.
                response_text = response.text or ""
                if response_text.strip():
                    return response_text
                candidates = getattr(response, "candidates", None) or []
                extracted: list[str] = []
                diagnostics: list[str] = []
                for candidate in candidates:
                    content = getattr(candidate, "content", None)
                    finish = getattr(candidate, "finish_reason", None)
                    diagnostics.append(f"finish={finish}")
                    for part in getattr(content, "parts", None) or []:
                        text_value = getattr(part, "text", None)
                        if text_value:
                            extracted.append(str(text_value))
                        else:
                            diagnostics.append(
                                "part="
                                f"{type(part).__name__},function_call="
                                f"{bool(getattr(part, 'function_call', None))}"
                            )
                if extracted:
                    return "\n".join(extracted)
                prompt_feedback = getattr(response, "prompt_feedback", None)
                block_reason = getattr(prompt_feedback, "block_reason", None)
                raise ProviderError(
                    "Vertex não retornou texto de rota "
                    f"(parsed={type(parsed).__name__},block={block_reason},{','.join(diagnostics)[:120]})."
                )

            raw = await asyncio.to_thread(invoke_google)
        elif self.mode == "local":
            body = json.dumps(
                {
                    "model": self.model,
                    "messages": [{"role": "user", "content": instruction}],
                    "format": "json",
                    "stream": False,
                    "options": {"temperature": 0},
                }
            ).encode()
            request = Request(
                f"{self.ollama_base_url}/api/chat",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            def invoke_ollama() -> str:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    result = json.loads(response.read())
                return str(result.get("message", {}).get("content", ""))

            raw = await asyncio.to_thread(invoke_ollama)
        else:
            raise ProviderError("Provider de roteamento não suportado.")
        try:
            # Vertex may return valid structured content wrapped in a Markdown
            # fence or with a short preamble despite response_mime_type. Extract
            # the bounded JSON object before validating the route.
            candidate = raw.strip().lstrip("\ufeff")
            candidate = re.sub(r"```(?:json)?\s*|\s*```", "", candidate, flags=re.IGNORECASE)
            decoder = json.JSONDecoder()
            plan = None
            for offset, char in enumerate(candidate):
                if char != "{":
                    continue
                try:
                    decoded, _ = decoder.raw_decode(candidate[offset:])
                except json.JSONDecodeError:
                    continue
                if isinstance(decoded, dict):
                    plan = decoded
                    break
            if plan is None:
                raise ValueError("Nenhum objeto JSON de rotas encontrado.")
            if not isinstance(plan, dict):
                raise ValueError("Plano deve ser objeto JSON.")

            # Only two whitelisted intents are accepted. Normalize common
            # Vertex/LLM JSON variations and do not delegate from free-form text.
            def as_route(value: Any) -> bool:
                if isinstance(value, bool):
                    return value
                if isinstance(value, str):
                    normalized_value = value.strip().casefold()
                    if normalized_value in {"true", "yes", "sim", "1"}:
                        return True
                    if normalized_value in {"false", "no", "não", "nao", "0"}:
                        return False
                if isinstance(value, int) and value in {0, 1}:
                    return bool(value)
                raise ValueError("Campo de rota inválido.")

            schedule = as_route(plan.get("schedule", plan.get("agenda", False)))
            faq = as_route(plan.get("faq", plan.get("policy", False)))
            if not schedule and not faq:
                faq = True
            return schedule, faq
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ProviderError(
                "O modelo retornou plano de coordenação inválido "
                f"({type(exc).__name__}: {str(exc)[:100]})."
            ) from exc

    async def ask(self, message: str, history: list[str] | None = None) -> AgentResult:
        del history
        start = time.monotonic()
        budget = DelegationBudget()
        deadline = Deadline(self.timeout_seconds)
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
            word in normalized
            for word in (
                "agenda",
                "palestra",
                "sessão",
                "sessões",
                "após",
                "sugira",
                "sugerir",
                "recomende",
                "recomendar",
                "iniciante",
                "iniciantes",
                "trilha",
                "horário",
            )
        )
        has_policy_intent = any(
            word in normalized
            for word in (
                "regra",
                "regras",
                "política",
                "politica",
                "acessibilidade",
                "cancelar",
                "cancelamento",
                "inscrição",
                "inscricao",
                "alimentação",
                "alimentacao",
            )
        )
        mixed_intent = has_schedule_intent and faq_intent and " e " in normalized
        route_error: str | None = None
        if self.mode in {"live", "local"}:
            try:
                async with asyncio.timeout(deadline.remaining()):
                    is_schedule, is_faq = await self._route_with_model(message)
            except Exception as exc:
                # Safe deterministic recovery keeps the demo usable when model
                # output is malformed. The model remains first choice; fallback
                # only routes to read-only specialists using explicit intent.
                is_schedule = has_schedule_intent
                is_faq = has_policy_intent or faq_intent or not is_schedule
                route_fallback = True
                route_error = f"{type(exc).__name__}:{str(exc)[:100]}"
            else:
                route_fallback = False
        else:
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
                        # Cloud Run scale-from-zero and low-CPU instances need
                        # more than three seconds to start Python and initialize
                        # the stdio MCP handshake. Keep within the request budget.
                        timeout_seconds=min(self.timeout_seconds, 10.0),
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
                    "fallback": route_fallback if self.mode in {"live", "local"} else False,
                    "route_fallback_reason": (
                        route_error if self.mode in {"live", "local"} else None
                    ),
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
