from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas import Session


@pytest.fixture
def records() -> list[dict[str, object]]:
    path = Path(__file__).parents[1] / "app" / "data" / "sessions.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def sessions(records: list[dict[str, object]]) -> list[Session]:
    return [Session.model_validate(item) for item in records]


@pytest.fixture
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    settings = Settings(database=tmp_path / "test.sqlite3")
    with TestClient(create_app(settings), headers={"origin": "http://testserver"}) as test_client:
        yield test_client
