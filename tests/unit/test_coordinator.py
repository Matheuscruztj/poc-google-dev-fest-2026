from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agent import ProviderError
from app.agents.coordinator import CoordinatorAgent, DelegationBudget
from app.resilience import CircuitBreaker


@pytest.mark.anyio
async def test_multi_coordinator_uses_mcp_and_never_writes(sessions):
    agent = CoordinatorAgent(sessions, use_mcp=True)
    result = await agent.ask("Quero palestras de IA após 14h")
    assert result.error is None
    assert result.mode == "offline:multi"
    assert result.trace["tools"] == ["delegate:schedule_agent", "mcp.list_sessions"]
    assert result.session_ids
    assert result.trace["reservation_writes"] == 0


@pytest.mark.anyio
async def test_multi_coordinator_routes_faq_with_verified_source(sessions):
    result = await CoordinatorAgent(sessions, use_mcp=False).ask(
        "Que recursos de acessibilidade existem?"
    )
    assert result.error is None
    assert result.sources[0]["document"] == "acessibilidade.md"
    assert result.trace["tools"] == ["delegate:faq_agent", "faq.search_policy"]


@pytest.mark.anyio
@pytest.mark.parametrize("provider", ["live", "local"])
@pytest.mark.anyio
async def test_multi_coordinator_rejects_unconfigured_providers(sessions, provider):
    result = await CoordinatorAgent(sessions, mode=provider).ask("Palestras de IA")
    assert result.error == f"multi_{provider}_unavailable"
    assert result.trace["fallback"] is True
    assert result.trace["tools"] == []


@pytest.mark.anyio
async def test_open_mcp_circuit_returns_verified_partial_faq(sessions):
    breaker = CircuitBreaker()
    for _ in range(3):
        breaker.failure()
    result = await CoordinatorAgent(sessions, use_mcp=True, circuit_breaker=breaker).ask(
        "Palestras após 14h e quais são as opções de acessibilidade?"
    )
    assert result.error is not None
    assert "Agenda indisponível" in result.answer
    assert result.sources[0]["document"] == "acessibilidade.md"
    assert result.trace["partial"] is True
    assert result.session_ids == []


def test_shared_delegation_budget_stops_cycles():
    budget = DelegationBudget(max_delegations=3, max_tool_calls=3)
    for _ in range(3):
        budget.delegate("faq_agent")
    with pytest.raises(ProviderError, match="delegações"):
        budget.delegate("faq_agent")


def test_multi_schema_is_additive_and_single_remains_default():
    from app.schemas import ChatRequest

    assert ChatRequest(message="oi").architecture == "single"
    with pytest.raises(ValidationError):
        ChatRequest(message="oi", architecture="other")
