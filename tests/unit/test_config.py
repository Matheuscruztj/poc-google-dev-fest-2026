from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings


def test_defaults_are_offline_and_create_only_runtime_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = tmp_path / "nested" / "eventops.sqlite3"
    monkeypatch.setenv("EVENTOPS_DATABASE", str(runtime))
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("EVENTOPS_AGENT_MODE", raising=False)

    settings = Settings.from_env()

    assert settings.mode == settings.agent_mode == "offline"
    assert settings.database == runtime
    assert runtime.parent.is_dir()
    assert list(runtime.parent.iterdir()) == []


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("EVENTOPS_MODE", "cloud", "EVENTOPS_MODE"),
        ("EVENTOPS_PORT", "abc", "inteiros"),
        ("EVENTOPS_PORT", "65536", "entre 1 e 65535"),
        ("EVENTOPS_AGENT_MODE", "remote", "EVENTOPS_AGENT_MODE"),
        ("EVENTOPS_SEED_CATALOG", "maybe", "EVENTOPS_SEED_CATALOG"),
        ("EVENTOPS_AGENT_TIMEOUT_SECONDS", "0", "EVENTOPS_AGENT_TIMEOUT_SECONDS"),
        ("EVENTOPS_COOKIE_SECURE", "perhaps", "EVENTOPS_COOKIE_SECURE"),
        ("EVENTOPS_AGENT_MODEL", "bad model", "EVENTOPS_AGENT_MODEL"),
        ("OLLAMA_CONTEXT_LENGTH", "512", "OLLAMA_CONTEXT_LENGTH"),
        ("OLLAMA_CONTEXT_LENGTH", "not-number", "OLLAMA_CONTEXT_LENGTH"),
    ],
)
def test_invalid_configuration_fails_clearly(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    key: str,
    value: str,
    message: str,
) -> None:
    monkeypatch.setenv("EVENTOPS_DATABASE", str(tmp_path / "db.sqlite3"))
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError, match=message):
        Settings.from_env()


def test_live_mode_requires_key_but_offline_does_not(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("EVENTOPS_DATABASE", str(tmp_path / "db.sqlite3"))
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("EVENTOPS_AGENT_MODE", "offline")
    assert Settings.from_env().google_api_key is None
    monkeypatch.setenv("EVENTOPS_AGENT_MODE", "live")
    with pytest.raises(ValueError, match="GOOGLE_API_KEY"):
        Settings.from_env()
    monkeypatch.setenv("EVENTOPS_AGENT_MODE", "local")
    assert Settings.from_env().agent_mode == "local"


def test_unwritable_database_parent_fails_clearly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    parent_file = tmp_path / "not-a-directory"
    parent_file.write_text("x", encoding="utf-8")
    monkeypatch.setenv("EVENTOPS_DATABASE", str(parent_file / "db.sqlite3"))
    with pytest.raises(ValueError, match="diretório gravável"):
        Settings.from_env()


def test_allowed_origins_are_normalized_and_validated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("EVENTOPS_DATABASE", str(tmp_path / "db.sqlite3"))
    monkeypatch.setenv("EVENTOPS_ALLOWED_ORIGINS", " https://demo.example/ ,http://localhost:8080 ")
    assert Settings.from_env().allowed_origins == (
        "https://demo.example",
        "http://localhost:8080",
    )
    monkeypatch.setenv("EVENTOPS_ALLOWED_ORIGINS", "javascript:alert(1)")
    with pytest.raises(ValueError, match="origem inválida"):
        Settings.from_env()


def test_postgres_url_is_accepted_without_local_sqlite_writability(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("EVENTOPS_DATABASE_URL", "postgresql://demo:secret@127.0.0.1/eventops")
    monkeypatch.setenv("EVENTOPS_DATABASE", str(tmp_path / "not-created" / "db.sqlite"))
    settings = Settings.from_env()
    assert settings.database_url == "postgresql://demo:secret@127.0.0.1/eventops"
    assert not settings.database.parent.exists()


def test_database_url_rejects_non_postgres_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVENTOPS_DATABASE_URL", "sqlite:///tmp/eventops.db")
    with pytest.raises(ValueError, match="PostgreSQL"):
        Settings.from_env()
