"""Build the package and verify its installed wheel outside the checkout."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from candidate import candidate_digest


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def verify_archive_contents(artifacts: list[Path]) -> dict[str, str]:
    required = (
        "app/data/sessions.json",
        "app/data/faq_metadata.json",
        "app/data/model_prices.json",
        "app/data/faq/acessibilidade.md",
        "app/static/index.html",
        "app/static/styles.css",
        "app/static/app.js",
        "app/migrations/0001_initial.sql",
        "app/migrations/0002_chat_sessions.sql",
        "mcp_server/server.py",
    )
    data_hashes = {
        resource: hashlib.sha256(Path(resource).read_bytes()).hexdigest() for resource in required
    }
    for artifact in artifacts:
        if artifact.suffix == ".whl":
            with zipfile.ZipFile(artifact) as archive:
                names = archive.namelist()
                data = {name: archive.read(name) for name in names}
        else:
            with tarfile.open(artifact, "r:gz") as archive:
                members = [member for member in archive.getmembers() if member.isfile()]
                names = [member.name for member in members]
                data = {}
                for member in members:
                    extracted = archive.extractfile(member)
                    if extracted is not None:
                        data[member.name] = extracted.read()
        normalized = {name.split("/", 1)[-1]: name for name in names}
        for resource in required:
            packaged_name = resource if artifact.suffix == ".whl" else normalized.get(resource)
            if not packaged_name or packaged_name not in data:
                raise RuntimeError(f"Recurso ausente em {artifact.name}: {resource}")
            if hashlib.sha256(data[packaged_name]).hexdigest() != data_hashes[resource]:
                raise RuntimeError(f"Hash de recurso divergente em {artifact.name}: {resource}")
        for name in names:
            lower = name.lower()
            if (
                lower.endswith((".sqlite", ".sqlite3", ".db", ".env", ".log", ".jsonl"))
                or "/reports/" in f"/{lower}"
                or "/tests/" in f"/{lower}"
            ):
                raise RuntimeError(f"Arquivo de runtime/desenvolvimento empacotado: {name}")
    return data_hashes


def verify_required_resources() -> list[str]:
    from importlib.resources import files

    from app.data_validation import validate_faq_catalog

    package = files("app")
    resources = [
        package.joinpath("data/sessions.json"),
        package.joinpath("data/faq_metadata.json"),
        package.joinpath("data/model_prices.json"),
        package.joinpath("migrations/0001_initial.sql"),
        package.joinpath("migrations/0002_chat_sessions.sql"),
        package.joinpath("static/index.html"),
        package.joinpath("static/styles.css"),
        package.joinpath("static/app.js"),
    ]
    missing = [str(resource) for resource in resources if not resource.is_file()]
    if missing:
        raise RuntimeError(f"Recursos obrigatórios ausentes: {', '.join(missing)}")
    return validate_faq_catalog()


def main() -> int:
    faq_documents = verify_required_resources()
    subprocess.run([sys.executable, "-m", "build", "--sdist", "--wheel"], check=True)
    artifacts = sorted([*Path("dist").glob("*.whl"), *Path("dist").glob("*.tar.gz")])
    if len(artifacts) != 2:
        raise RuntimeError("O build deve produzir exatamente um wheel e um sdist.")
    digests = {
        artifact.name: hashlib.sha256(artifact.read_bytes()).hexdigest() for artifact in artifacts
    }
    data_hashes = verify_archive_contents(artifacts)
    wheel = next(path.resolve() for path in artifacts if path.suffix == ".whl")
    with TemporaryDirectory(prefix="eventops-wheel-smoke-") as temporary:
        root = Path(temporary)
        environment = root / "venv"
        subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
        python = environment / "bin" / "python"
        subprocess.run([str(python), "-m", "pip", "install", "--quiet", str(wheel)], check=True)
        subprocess.run([str(python), "-m", "pip", "check"], cwd=root, check=True)
        import_result = subprocess.run(
            [
                str(python),
                "-c",
                "import app; import mcp_server.server; print(app.__file__)",
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        if not import_result.stdout.strip().startswith(str(environment)):
            raise RuntimeError("O pacote importado não veio do ambiente temporário.")

        port = free_port()
        runtime = root / "runtime"
        env = dict(
            os.environ,
            EVENTOPS_DATABASE=str(runtime / "eventops.sqlite3"),
            EVENTOPS_PORT=str(port),
            EVENTOPS_SEED_CATALOG="true",
        )
        server = subprocess.Popen(
            [
                str(environment / "bin" / "uvicorn"),
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=root,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        base_url = f"http://127.0.0.1:{port}"
        try:
            for _ in range(80):
                try:
                    with urllib.request.urlopen(f"{base_url}/health", timeout=1) as response:
                        assert response.status == 200
                    break
                except OSError as exc:
                    if server.poll() is not None:
                        raise RuntimeError(
                            "O servidor instalado encerrou antes do health check."
                        ) from exc
                    time.sleep(0.1)
            else:
                raise RuntimeError("O servidor instalado não ficou saudável a tempo.")

            with urllib.request.urlopen(f"{base_url}/api/sessions", timeout=3) as response:
                assert len(json.load(response)["sessions"]) == 20
            with sqlite3.connect(runtime / "eventops.sqlite3") as database:
                assert database.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 20
            with urllib.request.urlopen(base_url, timeout=3) as response:
                assert "DEMO OFFLINE" in response.read().decode()
            request = urllib.request.Request(
                f"{base_url}/api/faq",
                data=b'{"question":"acessibilidade"}',
                headers={"content-type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=3) as response:
                assert json.load(response)["sources"]
            with urllib.request.urlopen(f"{base_url}/static/app.js", timeout=3) as response:
                assert "textContent" in response.read().decode()
            with urllib.request.urlopen(f"{base_url}/openapi.json", timeout=3) as response:
                assert "/api/reservations/preview" in json.load(response)["paths"]
        finally:
            server.terminate()
            server.wait(timeout=5)
    report = {
        "status": "passed",
        "candidate_sha256": candidate_digest(),
        "artifacts": digests,
        "wheel_installed_outside_checkout": True,
        "import_origin": import_result.stdout.strip(),
        "pip_check": "passed",
        "data_hashes": data_hashes,
        "faq_documents": faq_documents,
        "smoke": ["health", "sessions", "index", "static_js", "faq", "openapi"],
    }
    report_path = Path("reports/build.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
