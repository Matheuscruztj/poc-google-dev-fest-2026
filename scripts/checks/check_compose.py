"""Build and smoke the offline Compose image with an isolated SQLite volume."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.checks.candidate import candidate_digest  # noqa: E402


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def main() -> int:
    if shutil.which("docker") is None:
        raise RuntimeError("Docker Compose é obrigatório para make pre-push.")
    port = free_port()
    project = f"eventops-smoke-{os.getpid()}"
    environment = dict(
        os.environ,
        COMPOSE_PROJECT_NAME=project,
        EVENTOPS_PORT=str(port),
        EVENTOPS_AGENT_MODE="offline",
        EVENTOPS_SEED_CATALOG="true",
    )
    base = f"http://127.0.0.1:{port}"
    try:
        subprocess.run(
            ["docker", "compose", "up", "--build", "-d", "app"],
            cwd=ROOT,
            env=environment,
            check=True,
        )
        container_id = subprocess.run(
            ["docker", "compose", "ps", "-q", "app"],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        run_as = subprocess.run(
            ["docker", "inspect", "--format", "{{.Config.User}}", container_id],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if run_as != "10001:10001":
            raise RuntimeError(f"O container executa com usuário inesperado: {run_as!r}.")
        runtime_env = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{range .Config.Env}}{{println .}}{{end}}",
                container_id,
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        if "PORT=8000" not in runtime_env:
            raise RuntimeError("O container não recebeu a porta configurada por PORT.")
        for _ in range(90):
            try:
                with urllib.request.urlopen(f"{base}/health", timeout=2) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(1)
        else:
            raise RuntimeError("O container Compose não ficou saudável em 90 segundos.")
        with urllib.request.urlopen(f"{base}/api/sessions", timeout=3) as response:
            sessions = json.load(response)["sessions"]
        if len(sessions) != 20:
            raise RuntimeError("O container não expôs as 20 sessões persistidas em SQLite.")
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())

        def post(path: str, payload: dict[str, object]) -> dict[str, object]:
            request = urllib.request.Request(
                f"{base}{path}",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json", "Origin": base},
                method="POST",
            )
            with opener.open(request, timeout=5) as response:
                result = json.load(response)
            if not isinstance(result, dict):
                raise RuntimeError(f"Resposta inesperada em {path}.")
            return result

        multi = post("/api/chat", {"message": "Palestras de IA após 14h", "architecture": "multi"})
        if multi.get("error") is not None or multi.get("mode") != "offline:multi":
            raise RuntimeError("A arquitetura multi/MCP não funcionou no container.")

        preview = post("/api/reservations/preview", {"session_id": "S01"})
        key = "compose-smoke-key-0001"
        request_payload = {
            "session_id": "S01",
            "confirmation_token": preview["confirmation_token"],
            "idempotency_key": key,
        }
        first_receipt = post("/api/reservations", request_payload)
        replay = post("/api/reservations", request_payload)
        if replay.get("receipt_id") != first_receipt.get("receipt_id") or not replay.get(
            "replayed"
        ):
            raise RuntimeError("Retry HTTP não retornou comprovante idempotente.")
        package_write = subprocess.run(
            [
                "docker",
                "exec",
                container_id,
                "python",
                "-c",
                "from pathlib import Path; import app; p=Path(app.__file__).parent/'write-probe'; "
                "p.write_text('bad')",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if package_write.returncode == 0:
            raise RuntimeError("Os recursos instalados do pacote permitem escrita pelo app user.")
        database = subprocess.run(
            [
                "docker",
                "exec",
                container_id,
                "python",
                "-c",
                "import sqlite3; c=sqlite3.connect('/var/lib/eventops/eventops.sqlite3'); "
                "print(c.execute('select count(*) from reservations').fetchone()[0])",
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if database != "1":
            raise RuntimeError("Retry de reserva criou mais de uma reserva SQLite.")
        subprocess.run(
            ["docker", "compose", "restart", "app"], cwd=ROOT, env=environment, check=True
        )
        for _ in range(45):
            try:
                with urllib.request.urlopen(f"{base}/health", timeout=2) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(1)
        with urllib.request.urlopen(f"{base}/api/sessions", timeout=3) as response:
            if len(json.load(response)["sessions"]) != 20:
                raise RuntimeError("O catálogo não persistiu após reiniciar o container.")
        replay_after_restart = post("/api/reservations", request_payload)
        if replay_after_restart.get("receipt_id") != first_receipt.get("receipt_id"):
            raise RuntimeError(
                "O comprovante idempotente não persistiu após reiniciar o container."
            )
        post("/api/chat", {"message": "Quais são as trilhas do evento?"})
        history = subprocess.run(
            [
                "docker",
                "exec",
                container_id,
                "python",
                "-c",
                "import os,sqlite3; c=sqlite3.connect(os.environ['EVENTOPS_DATABASE']); "
                "print(c.execute('SELECT COUNT(*), COUNT(DISTINCT demo_session_hash) "
                "FROM demo_chat_messages').fetchone())",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if history != "(4, 1)":
            raise RuntimeError("O histórico/cookie de chat não persistiu após reinício.")
        image_id = subprocess.run(
            [
                "docker",
                "image",
                "inspect",
                "--format",
                "{{.Id}}",
                f"{project}-app",
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        if not image_id.startswith("sha256:"):
            raise RuntimeError("Docker não retornou o ID imutável da imagem Compose.")
        evidence = {
            "status": "passed",
            "candidate_sha256": candidate_digest(),
            "image_id": image_id,
            "container_id": container_id,
        }
        Path("reports").mkdir(exist_ok=True)
        Path("reports/compose.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(
            "Compose offline smoke: health, catálogo/MCP, histórico e reinício aprovados. "
            f"Image id: {image_id}"
        )
        return 0
    finally:
        subprocess.run(
            ["docker", "compose", "down", "-v", "--remove-orphans"],
            cwd=ROOT,
            env=environment,
            check=False,
        )


if __name__ == "__main__":
    raise SystemExit(main())
