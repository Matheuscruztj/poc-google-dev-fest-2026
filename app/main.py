"""FastAPI application for the offline EventOps AI demonstration."""

from __future__ import annotations

import asyncio
import secrets
import time
from contextlib import asynccontextmanager
from importlib.resources import files
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.agent import make_agent
from app.agents.coordinator import CoordinatorAgent
from app.config import Settings
from app.data_validation import load_session_seed, validate_faq_catalog
from app.faq import search_faq
from app.metrics import configure_file_logging
from app.reservations import ReservationError, ReservationService, token_hash
from app.resilience import CircuitBreaker
from app.schedule import sessions_from_records, suggest_schedule
from app.schemas import ChatRequest, FAQRequest, PreviewRequest, ReservationRequest, ScheduleRequest
from app.storage import Storage

COOKIE_NAME = "eventops_demo"


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings.from_env()
    validate_faq_catalog()
    storage = Storage(config.database_url or config.database)
    if config.seed_catalog:
        storage.seed_sessions_if_empty(load_session_seed())
    sessions = sessions_from_records(storage.list_sessions())
    reservation_service = ReservationService(storage, config.confirmation_ttl_seconds)
    mcp_breaker = CircuitBreaker()
    trace_dir = Path("/tmp/eventops") if config.database_url else config.database.parent
    configure_file_logging(trace_dir / "agent-traces.jsonl")
    chat_history: dict[str, list[str]] = {}
    chat_locks: dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> Any:
        yield

    application = FastAPI(title="EventOps AI", version="0.1.0", lifespan=lifespan)
    application.state.settings = config
    application.state.storage = storage
    application.state.sessions = sessions
    application.state.reservations = reservation_service
    application.state.mcp_breaker = mcp_breaker
    application.state.chat_history = chat_history

    @application.middleware("http")
    async def request_id_middleware(request: Request, call_next: Any) -> Any:
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        demo_cookie = getattr(request.state, "demo_cookie", None)
        if demo_cookie:
            response.set_cookie(
                COOKIE_NAME,
                demo_cookie,
                httponly=True,
                secure=config.cookie_secure,
                samesite="lax",
                max_age=60 * 60 * 24,
                path="/",
            )
        return response

    static_root = files("app").joinpath("static")
    application.mount("/static", StaticFiles(directory=str(static_root)), name="static")

    def ensure_demo_user(request: Request) -> tuple[str, str]:
        raw = request.cookies.get(COOKIE_NAME)
        now = time.time()
        context = storage.demo_session_context(token_hash(raw) if raw else None, now)
        if context:
            request.state.demo_cookie = raw
            return context[1], context[0]
        raw = secrets.token_urlsafe(32)
        user = f"{config.demo_user}-{secrets.token_hex(8)}"
        storage.create_demo_session(
            token_hash(raw),
            user,
            now,
            now + 86400,
        )
        request.state.demo_cookie = raw
        return user, raw

    def verify_origin(request: Request) -> None:
        origin = request.headers.get("origin")
        allowed = {*config.allowed_origins, str(request.base_url).rstrip("/")}
        if not origin or origin.rstrip("/") not in allowed:
            raise ReservationError(
                403, "origin_not_allowed", "Origem ausente ou não permitida para esta operação."
            )

    def error_response(request: Request, status_code: int, code: str, message: str) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content={
                "error": {
                    "code": code,
                    "message": message,
                    "request_id": getattr(request.state, "request_id", "unavailable"),
                }
            },
        )

    @application.exception_handler(ReservationError)
    async def reservation_error(request: Request, exc: ReservationError) -> JSONResponse:
        return error_response(request, exc.status_code, exc.code, str(exc))

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, _: RequestValidationError) -> JSONResponse:
        return error_response(
            request, 422, "invalid_request", "A solicitação contém campos ou valores inválidos."
        )

    @application.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        messages = {
            404: ("not_found", "O recurso solicitado não foi encontrado."),
            405: ("method_not_allowed", "O método não é permitido para este recurso."),
        }
        code, message = messages.get(
            exc.status_code, ("http_error", "Não foi possível concluir a solicitação.")
        )
        return error_response(request, exc.status_code, code, message)

    @application.exception_handler(Exception)
    async def unexpected_error(request: Request, _: Exception) -> JSONResponse:
        return error_response(
            request, 500, "internal_error", "Ocorreu um erro interno. Tente novamente."
        )

    @application.get("/")
    def index() -> FileResponse:
        return FileResponse(str(static_root.joinpath("index.html")))

    @application.get("/health")
    def health() -> dict[str, str]:
        storage.list_sessions()
        return {
            "status": "ok",
            "mode": config.mode,
            "agent_mode": config.agent_mode,
            "model": (
                config.agent_model
                if config.agent_mode == "live"
                else config.ollama_model
                if config.agent_mode == "local"
                else "none"
            ),
        }

    @application.get("/api/sessions")
    def list_sessions(track: str | None = None, level: str | None = None) -> dict[str, object]:
        current_sessions = sessions_from_records(storage.list_sessions())
        values = [
            item
            for item in current_sessions
            if (not track or item.track.casefold() == track.casefold())
            and (not level or item.level.casefold() == level.casefold())
        ]
        return {"sessions": [item.model_dump(mode="json") for item in values]}

    @application.post("/api/schedule")
    def schedule(body: ScheduleRequest) -> dict[str, Any]:
        current_sessions = sessions_from_records(storage.list_sessions())
        return suggest_schedule(
            current_sessions, track=body.track, level=body.level, after=body.after, limit=body.limit
        )

    @application.post("/api/faq")
    def faq(body: FAQRequest) -> dict[str, object]:
        return search_faq(body.question)

    @application.post("/api/chat")
    async def chat(body: ChatRequest, request: Request) -> JSONResponse:
        verify_origin(request)
        user, _ = ensure_demo_user(request)
        current_sessions = sessions_from_records(storage.list_sessions())
        current_agent = (
            CoordinatorAgent(
                current_sessions,
                mode=config.agent_mode,
                model=(config.ollama_model if config.agent_mode == "local" else config.agent_model),
                timeout_seconds=config.agent_timeout_seconds,
                circuit_breaker=mcp_breaker,
            )
            if body.architecture == "multi"
            else make_agent(
                current_sessions,
                config.agent_mode,
                config.agent_model,
                config.google_api_key,
                config.agent_timeout_seconds,
                config.ollama_base_url,
                config.ollama_model,
            )
        )
        _, browser_session = ensure_demo_user(request)
        if len(chat_history) > 4096:
            chat_history.clear()
            chat_locks.clear()
        lock = chat_locks.setdefault(browser_session, asyncio.Lock())
        async with lock:
            history = list(chat_history.get(browser_session, []))
            result = await current_agent.ask(body.message, history)
            history.extend([body.message, result.answer])
            chat_history[browser_session] = history[-8:]
        response = JSONResponse(
            content={
                "answer": result.answer,
                "session_ids": result.session_ids,
                "sources": result.sources,
                "reservation_proposal": result.reservation_proposal,
                "mode": result.mode,
                "error": result.error,
                "trace": result.trace,
            },
            status_code=200,
        )
        return response

    @application.post("/api/reservations/preview")
    def preview(body: PreviewRequest, request: Request) -> JSONResponse:
        verify_origin(request)
        user, _ = ensure_demo_user(request)
        result = reservation_service.preview(body.session_id, user)
        return JSONResponse(content=result)

    @application.post("/api/reservations")
    def reserve(body: ReservationRequest, request: Request) -> JSONResponse:
        verify_origin(request)
        user, _ = ensure_demo_user(request)
        result = reservation_service.reserve(
            body.session_id, user, body.confirmation_token, body.idempotency_key
        )
        return JSONResponse(content=result)

    return application


app = create_app()
