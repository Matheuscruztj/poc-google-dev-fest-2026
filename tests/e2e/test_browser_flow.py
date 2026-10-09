from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from collections.abc import Generator
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api", reason="instale o lock de desenvolvimento")
Browser = playwright.Browser
Page = playwright.Page
Route = playwright.Route
sync_playwright = playwright.sync_playwright
expect = playwright.expect

ROOT = Path(__file__).parents[2]


def available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@pytest.fixture(scope="session")
def browser() -> Generator[Browser, None, None]:
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch()
        yield instance
        instance.close()


@pytest.fixture
def demo_server(tmp_path: Path) -> Generator[tuple[str, Path], None, None]:
    port = available_port()
    database = tmp_path / "demo.sqlite3"
    environment = dict(
        os.environ,
        EVENTOPS_DATABASE=str(database),
        EVENTOPS_PORT=str(port),
        EVENTOPS_AGENT_MODE="offline",
    )
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        import urllib.error
        import urllib.request

        for _ in range(100):
            try:
                with urllib.request.urlopen(f"{base_url}/health", timeout=1) as response:
                    if response.status == 200:
                        break
            except (OSError, urllib.error.URLError):
                if server.poll() is not None:
                    pytest.fail("A API de demonstração encerrou antes de ficar pronta.")
                time.sleep(0.1)
        else:
            pytest.fail("A API de demonstração não ficou pronta a tempo.")
        yield base_url, database
    finally:
        server.terminate()
        server.wait(timeout=5)


def preserve_diagnostics(page: Page, name: str) -> None:
    output = ROOT / "test-results"
    output.mkdir(exist_ok=True)
    page.screenshot(path=output / f"{name}.png", full_page=True)


def open_reservation(page: Page) -> None:
    card = page.locator("#schedule-results .session-card").filter(has_text="S01").first
    card.get_by_role("button", name="Reservar").click()
    page.get_by_role("dialog").wait_for(state="visible")
    expect(page.get_by_role("button", name="Confirmar reserva")).to_be_enabled()


@pytest.mark.e2e
def test_reservation_retry_is_idempotent_and_capacity_is_shared(
    browser: Browser, demo_server: tuple[str, Path]
) -> None:
    base_url, database = demo_server
    context = browser.new_context()
    second_context = browser.new_context()
    page = context.new_page()
    try:
        page.goto(base_url, wait_until="networkidle")
        open_reservation(page)
        first_attempt = True

        def lose_first_response(route: Route) -> None:
            nonlocal first_attempt
            if first_attempt:
                first_attempt = False
                route.fetch()
                route.abort("failed")
                return
            route.continue_()

        page.route("**/api/reservations", lose_first_response)
        confirm_button = page.get_by_role("button", name="Confirmar reserva")
        confirm_button.click()
        page.locator("#reservation-message.error").wait_for(state="visible")
        confirm_button.click()
        page.get_by_text("solicitação repetida com segurança", exact=False).wait_for(
            state="visible"
        )

        with sqlite3.connect(database) as connection:
            assert connection.execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM idempotency").fetchone()[0] == 1

        other_page = second_context.new_page()
        other_page.goto(base_url, wait_until="networkidle")
        other_card = (
            other_page.locator("#schedule-results .session-card").filter(has_text="S01").first
        )
        other_card.get_by_role("button", name="Reservar").click()
        expect(other_page.get_by_role("button", name="Confirmar reserva")).to_be_enabled()
        with sqlite3.connect(database) as storage:
            storage.execute("UPDATE sessions SET capacity=1 WHERE id='S01'")
        other_page.get_by_role("button", name="Confirmar reserva").click()
        other_page.locator("#reservation-message.error").wait_for(state="visible")
        with sqlite3.connect(database) as storage:
            assert storage.execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == 1
    except Exception:
        preserve_diagnostics(page, "reservation-flow-failure")
        raise
    finally:
        second_context.close()
        context.close()


@pytest.mark.e2e
def test_mobile_layout_keeps_navigation_and_cards_usable(
    browser: Browser, demo_server: tuple[str, Path]
) -> None:
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    try:
        page.goto(demo_server[0], wait_until="networkidle")
        expect(page.get_by_role("navigation", name="Navegação principal")).to_be_visible()
        expect(page.get_by_role("link", name="Agenda", exact=True)).to_be_visible()
        columns = page.locator("#schedule-results").evaluate(
            "node => getComputedStyle(node).gridTemplateColumns.split(' ').length"
        )
        has_horizontal_overflow = page.evaluate(
            "document.documentElement.scrollWidth > window.innerWidth"
        )
        assert columns == 1
        assert not has_horizontal_overflow
    finally:
        context.close()


@pytest.mark.e2e
def test_untrusted_model_markup_is_rendered_as_text(
    browser: Browser, demo_server: tuple[str, Path]
) -> None:
    context = browser.new_context()
    page = context.new_page()
    try:
        page.goto(demo_server[0], wait_until="networkidle")
        payload = "<img src=x onerror=window.__owasp_xss=true>"
        page.route(
            "**/api/chat",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "answer": payload,
                        "session_ids": [],
                        "sources": [],
                        "reservation_proposal": None,
                        "mode": "offline",
                        "error": None,
                        "trace": {"delegations": 0},
                    }
                ),
            ),
        )
        page.get_by_label("Mensagem para o guia").fill(
            "Explique esta string fornecida pelo usuário"
        )
        page.get_by_role("button", name="Perguntar").click()
        expect(page.locator("#chat-results .chat-answer p")).to_have_text(payload)
        assert page.locator("#chat-results img").count() == 0
        assert page.evaluate("window.__owasp_xss === true") is False
    finally:
        context.close()
