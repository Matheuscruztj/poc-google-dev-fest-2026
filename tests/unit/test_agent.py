import json

import pytest

from app.agent import (
    AgentResult,
    OllamaProvider,
    ProviderError,
    SingleAgent,
    TransientProviderError,
    build_adk_agent,
    make_agent,
)
from app.evaluators import evaluate_case, load_cases
from app.metrics import Trace, redact
from app.schemas import Session
from app.tools import DemoTools


class FakeProvider:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    async def respond(self, message, tools: DemoTools, history):
        del message, tools, history
        if self.error:
            raise self.error
        return json.dumps(self.result, ensure_ascii=False), {"input_tokens": 12, "output_tokens": 7}


class RetryingProvider:
    def __init__(self):
        self.attempts = 0

    async def respond(self, message, tools, history):
        del message, history
        self.attempts += 1
        if self.attempts == 1:
            raise TransientProviderError("temporary read failure")
        tools.list_sessions(track="IA")
        return json.dumps(
            {"answer": "ok", "session_ids": ["S11"], "sources": [], "reservation_proposal": None}
        ), {"input_tokens": None, "output_tokens": None}


@pytest.fixture
def catalog(records):
    return [Session.model_validate(item) for item in records]


@pytest.mark.anyio
async def test_provider_fake_returns_valid_proposal(catalog):
    response = {
        "answer": "Confira esta palestra.",
        "session_ids": ["S11"],
        "sources": [],
        "reservation_proposal": "S11",
    }
    agent = SingleAgent(catalog, FakeProvider(response), "test", "fake-model")
    result = await agent.ask("Reserve uma palestra de IA")
    assert result.error is None
    assert result.session_ids == ["S11"]
    assert result.reservation_proposal == "S11"
    assert result.trace["input_tokens"] == 12


@pytest.mark.anyio
async def test_agent_retries_transient_read_provider_once(catalog):
    provider = RetryingProvider()
    result = await SingleAgent(catalog, provider, "test", "fake").ask("agenda IA")
    assert result.error is None
    assert result.trace["retries"] == 1
    assert provider.attempts == 2


@pytest.mark.anyio
async def test_unknown_session_id_is_rejected(catalog):
    response = {
        "answer": "ok",
        "session_ids": ["FAKE"],
        "sources": [],
        "reservation_proposal": None,
    }
    result = await SingleAgent(catalog, FakeProvider(response), "test", "fake").ask("pergunta")
    assert result.error == "O agente retornou IDs de sessão desconhecidos."
    assert result.trace["validated"] is False
    assert result.trace["fallback"] is True
    assert "FAKE" in result.trace["raw_output"]


@pytest.mark.anyio
async def test_unverified_source_is_rejected(catalog):
    response = {
        "answer": "Regra inventada.",
        "session_ids": [],
        "sources": [{"document": "secret.md", "section": "Fake", "excerpt": "invente"}],
        "reservation_proposal": None,
    }
    result = await SingleAgent(catalog, FakeProvider(response), "test", "fake").ask("pergunta")
    assert result.error == "O agente retornou uma fonte não verificada."
    assert result.sources == []


@pytest.mark.anyio
async def test_invalid_source_shape_is_rejected(catalog):
    response = {
        "answer": "Ok",
        "session_ids": [],
        "sources": [{"document": ["bad"], "section": "fake", "excerpt": "x"}],
        "reservation_proposal": None,
    }
    result = await SingleAgent(catalog, FakeProvider(response), "test", "fake").ask("pergunta")
    assert result.error == "A fonte não contém arquivo e seção válidos."


@pytest.mark.anyio
async def test_unknown_output_field_is_rejected(catalog):
    response = {
        "answer": "Ok",
        "session_ids": [],
        "sources": [],
        "reservation_proposal": None,
        "confirmation_token": "secret",
    }
    result = await SingleAgent(catalog, FakeProvider(response), "test", "fake").ask("pergunta")
    assert result.error == "Formato de resposta inválido."


@pytest.mark.anyio
async def test_conflicting_session_ids_are_rejected(catalog):
    response = {
        "answer": "Ok",
        "session_ids": ["S02", "S03"],
        "sources": [],
        "reservation_proposal": None,
    }
    result = await SingleAgent(catalog, FakeProvider(response), "test", "fake").ask("pergunta")
    assert result.error == "O agente retornou sessões com conflito de horário."


@pytest.mark.anyio
async def test_provider_error_is_not_reported_as_success(catalog):
    result = await SingleAgent(
        catalog, FakeProvider(error=ProviderError("offline failure")), "test", "fake"
    ).ask("pergunta")
    assert result.error == "offline failure"
    assert result.trace["status"] == "error"
    assert result.trace["fallback"] is True


def test_trace_redacts_api_and_confirmation_secrets():
    value = redact(
        {
            "google_api_key": "AIza123456789012345678901234567890",
            "confirmation_token": "abc-token",
            "text": "confirmation_token=secret",
        }
    )
    assert value["google_api_key"] == "[REDACTED]"
    assert value["confirmation_token"] == "[REDACTED]"
    assert "secret" not in value["text"]
    trace = Trace("offline", "none").finish(
        status="ok", raw_output="safe", validated=True, fallback=False
    )
    assert trace["input_tokens"] is None


def test_trace_file_omits_untrusted_raw_response(tmp_path, caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="eventops.trace"):
        Trace("offline", "none").finish(
            status="ok", raw_output="private user text", validated=True, fallback=False
        )
    assert "[OMITTED]" in caplog.text
    assert "private user text" not in caplog.text


def test_dataset_has_expected_cases_and_independent_failure_oracle():
    cases = load_cases(__import__("pathlib").Path("evals/cases.jsonl"))
    assert len(cases) == 40
    failed = AgentResult(
        "made up", ["NOT-A-SESSION"], [], None, "replay", {"tools": ["reserve_seat"]}
    )
    verdict = evaluate_case(cases[0], failed)
    assert verdict["passed"] is False


@pytest.mark.anyio
async def test_tool_budget_is_per_request_and_prohibited_tools_are_not_exposed(catalog):
    from app.agent import OfflineProvider

    tools = DemoTools(catalog)
    assert {tool.__name__ for tool in tools.adk_tools()} == {
        "list_sessions",
        "check_schedule",
        "search_policy",
    }
    _, usage = await OfflineProvider().respond("SIMULATE_TOOL_FAILURE", tools, [])
    assert tools.calls == ["search_policy"]
    assert usage == {"input_tokens": None, "output_tokens": None}


def test_adversarial_fixture_is_not_a_published_faq():
    from app.faq import load_chunks

    assert "prompt_injection.md" not in {chunk.document for chunk in load_chunks()}


def test_adk_agent_constructs_with_only_read_tools(catalog):
    pytest.importorskip("google.adk.agents")
    from google.adk.agents import Agent
    from google.genai import types

    adk_agent = build_adk_agent(Agent, types, "gemini-2.5-flash", DemoTools(catalog))
    assert adk_agent.name == "eventops_single_agent"
    assert len(adk_agent.tools) == 3
    assert {tool.__name__ for tool in adk_agent.tools} == {
        "list_sessions",
        "check_schedule",
        "search_policy",
    }


def test_local_mode_selects_ollama_provider(catalog):
    agent = make_agent(
        catalog,
        mode="local",
        model="gemini-2.5-flash",
        api_key=None,
        ollama_base_url="http://ollama:11434",
        ollama_model="qwen2.5:3b",
    )
    assert isinstance(agent.provider, OllamaProvider)
    assert agent.provider.base_url == "http://ollama:11434"
    assert agent.model == "qwen2.5:3b"


@pytest.mark.anyio
async def test_adk_runner_session_lifecycle_has_no_model_call(catalog):
    pytest.importorskip("google.adk.runners")
    from google.adk.agents import Agent
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    agent = build_adk_agent(Agent, types, "gemini-2.5-flash", DemoTools(catalog))
    service = InMemorySessionService()
    runner = Runner(agent=agent, app_name="eventops-test", session_service=service)
    session = await service.create_session(
        app_name="eventops-test", user_id="fake-user", session_id="fake-session"
    )
    assert session.id == "fake-session"
    await runner.close()
