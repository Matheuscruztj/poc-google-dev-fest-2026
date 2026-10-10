"""Typed environment configuration for the local demo."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    mode: str = "offline"
    database: Path = Path("var/eventops.sqlite3")
    database_url: str | None = None
    seed_catalog: bool = True
    host: str = "127.0.0.1"
    port: int = 8000
    demo_user: str = "participante-demo"
    confirmation_ttl_seconds: int = 300
    cookie_secure: bool = False
    allowed_origins: tuple[str, ...] = ()
    agent_mode: str = "offline"
    google_api_key: str | None = None
    google_vertex_ai: bool = False
    google_cloud_project: str | None = None
    google_cloud_location: str = "us-central1"
    agent_model: str = "gemini-2.5-flash"
    agent_timeout_seconds: int = 12
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_embedding_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:3b"
    ollama_context_length: int = 8192
    rag_mode: str = "lexical"
    rag_database_url: str | None = None
    embedding_provider: str = "ollama"
    embedding_model: str = "nomic-embed-text:latest"
    ollama_embedding_model: str = "nomic-embed-text:latest"

    @classmethod
    def from_env(cls) -> Settings:
        mode = os.getenv("EVENTOPS_MODE", "offline").strip().lower()
        if mode != "offline":
            raise ValueError("EVENTOPS_MODE aceita somente 'offline' nesta versão.")
        port_text = os.getenv("EVENTOPS_PORT", "8000")
        ttl_text = os.getenv("EVENTOPS_CONFIRMATION_TTL_SECONDS", "300")
        try:
            port, ttl = int(port_text), int(ttl_text)
        except ValueError as exc:
            raise ValueError(
                "EVENTOPS_PORT e EVENTOPS_CONFIRMATION_TTL_SECONDS devem ser inteiros."
            ) from exc
        if not 1 <= port <= 65535:
            raise ValueError("EVENTOPS_PORT deve estar entre 1 e 65535.")
        if ttl < 1:
            raise ValueError("EVENTOPS_CONFIRMATION_TTL_SECONDS deve ser positivo.")
        agent_mode = os.getenv("EVENTOPS_AGENT_MODE", "offline").strip().lower()
        if agent_mode not in {"offline", "live", "local"}:
            raise ValueError("EVENTOPS_AGENT_MODE aceita 'offline', 'local' ou 'live'.")
        try:
            agent_timeout = int(os.getenv("EVENTOPS_AGENT_TIMEOUT_SECONDS", "12"))
        except ValueError as exc:
            raise ValueError("EVENTOPS_AGENT_TIMEOUT_SECONDS deve ser inteiro.") from exc
        if not 1 <= agent_timeout <= 60:
            raise ValueError("EVENTOPS_AGENT_TIMEOUT_SECONDS deve estar entre 1 e 60.")
        api_key = os.getenv("GOOGLE_API_KEY")
        vertex_text = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "false").strip().lower()
        if vertex_text not in {"1", "true", "yes", "0", "false", "no"}:
            raise ValueError("GOOGLE_GENAI_USE_VERTEXAI deve ser booleano.")
        google_vertex_ai = vertex_text in {"1", "true", "yes"}
        google_cloud_project = os.getenv("GOOGLE_CLOUD_PROJECT") or None
        google_cloud_location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1").strip()
        if agent_mode == "live" and not api_key and not google_vertex_ai:
            raise ValueError("EVENTOPS_AGENT_MODE=live exige GOOGLE_API_KEY ou Vertex AI com ADC.")
        ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        ollama_embedding_base_url = os.getenv("OLLAMA_EMBEDDING_BASE_URL", ollama_base_url).rstrip(
            "/"
        )
        ollama_model = os.getenv("OLLAMA_MODEL", "qwen2.5:3b").strip()
        if not ollama_model or len(ollama_model) > 128:
            raise ValueError("OLLAMA_MODEL deve conter de 1 a 128 caracteres.")
        try:
            ollama_context_length = int(os.getenv("OLLAMA_CONTEXT_LENGTH", "8192"))
        except ValueError as exc:
            raise ValueError("OLLAMA_CONTEXT_LENGTH deve ser inteiro.") from exc
        if not 1024 <= ollama_context_length <= 32768:
            raise ValueError("OLLAMA_CONTEXT_LENGTH deve estar entre 1024 e 32768.")
        rag_mode = os.getenv("EVENTOPS_RAG_MODE", "lexical").strip().lower()
        if rag_mode not in {"lexical", "hybrid"}:
            raise ValueError("EVENTOPS_RAG_MODE aceita 'lexical' ou 'hybrid'.")
        rag_database_url = os.getenv("EVENTOPS_RAG_DATABASE_URL") or None
        if rag_database_url and not rag_database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("EVENTOPS_RAG_DATABASE_URL precisa usar PostgreSQL.")
        embedding_provider = os.getenv("EVENTOPS_EMBEDDING_PROVIDER", "ollama").strip().lower()
        if embedding_provider not in {"ollama", "google"}:
            raise ValueError("EVENTOPS_EMBEDDING_PROVIDER aceita 'ollama' ou 'google'.")
        default_embedding_model = (
            "gemini-embedding-001" if embedding_provider == "google" else "nomic-embed-text:latest"
        )
        embedding_model_value = (
            os.getenv("EVENTOPS_EMBEDDING_MODEL")
            or os.getenv("OLLAMA_EMBEDDING_MODEL")
            or default_embedding_model
        )
        embedding_model = embedding_model_value.strip()
        if not embedding_model or len(embedding_model) > 128:
            raise ValueError("OLLAMA_EMBEDDING_MODEL deve conter de 1 a 128 caracteres.")
        if embedding_provider == "google" and not api_key:
            raise ValueError("Embeddings Google exigem GOOGLE_API_KEY configurada.")
        if rag_mode == "hybrid" and not rag_database_url:
            raise ValueError("EVENTOPS_RAG_MODE=hybrid exige EVENTOPS_RAG_DATABASE_URL.")
        host = os.getenv("EVENTOPS_HOST", "127.0.0.1").strip()
        if not host or any(char.isspace() for char in host):
            raise ValueError("EVENTOPS_HOST deve ser um hostname ou endereço válido.")
        demo_user = os.getenv("EVENTOPS_DEMO_USER", "participante-demo").strip()
        if not demo_user or len(demo_user) > 80:
            raise ValueError("EVENTOPS_DEMO_USER deve conter de 1 a 80 caracteres.")
        model = os.getenv("EVENTOPS_AGENT_MODEL", "gemini-2.5-flash").strip()
        if not model or not re.fullmatch(r"[A-Za-z0-9._/-]{1,128}", model):
            raise ValueError("EVENTOPS_AGENT_MODEL contém caracteres inválidos.")
        secure_text = os.getenv("EVENTOPS_COOKIE_SECURE", "false").strip().lower()
        if secure_text not in {"1", "true", "yes", "0", "false", "no"}:
            raise ValueError("EVENTOPS_COOKIE_SECURE deve ser booleano.")
        allowed_origins = tuple(
            origin.strip().rstrip("/")
            for origin in os.getenv("EVENTOPS_ALLOWED_ORIGINS", "").split(",")
            if origin.strip()
        )
        for origin in allowed_origins:
            parsed = urlsplit(origin)
            try:
                port_is_valid = parsed.port is None or 1 <= parsed.port <= 65535
            except ValueError:
                port_is_valid = False
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.username
                or parsed.password
                or not port_is_valid
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("EVENTOPS_ALLOWED_ORIGINS contém uma origem inválida.")
        database_url = os.getenv("EVENTOPS_DATABASE_URL") or None
        if database_url and not database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("EVENTOPS_DATABASE_URL precisa usar PostgreSQL.")
        database = Path(
            os.getenv(
                "EVENTOPS_DATABASE",
                "/tmp/eventops.sqlite3" if database_url else "var/eventops.sqlite3",
            )
        ).expanduser()
        if not database_url:
            try:
                database.parent.mkdir(parents=True, exist_ok=True)
                if not database.parent.is_dir():
                    raise OSError("diretório não existe")
                probe = database.parent / f".eventops-write-check-{os.getpid()}"
                probe.touch(exist_ok=False)
                probe.unlink()
            except OSError as exc:
                raise ValueError("EVENTOPS_DATABASE deve apontar para diretório gravável.") from exc
        seed_text = os.getenv("EVENTOPS_SEED_CATALOG", "true").strip().lower()
        if seed_text not in {"1", "true", "yes", "0", "false", "no"}:
            raise ValueError("EVENTOPS_SEED_CATALOG deve ser booleano.")
        return cls(
            mode=mode,
            database=database,
            database_url=database_url,
            seed_catalog=seed_text in {"1", "true", "yes"},
            host=host,
            port=port,
            demo_user=demo_user,
            confirmation_ttl_seconds=ttl,
            cookie_secure=secure_text in {"1", "true", "yes"},
            allowed_origins=allowed_origins,
            agent_mode=agent_mode,
            google_api_key=api_key,
            google_vertex_ai=google_vertex_ai,
            google_cloud_project=google_cloud_project,
            google_cloud_location=google_cloud_location,
            agent_model=model,
            agent_timeout_seconds=agent_timeout,
            ollama_base_url=ollama_base_url,
            ollama_embedding_base_url=ollama_embedding_base_url,
            ollama_model=ollama_model,
            ollama_context_length=ollama_context_length,
            rag_mode=rag_mode,
            rag_database_url=rag_database_url,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            ollama_embedding_model=embedding_model,
        )
