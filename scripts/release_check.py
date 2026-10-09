"""Bind local eval, build and container evidence to the current source candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from candidate import ROOT, candidate_digest


def read_report(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"Evidência ausente: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Relatório inválido: {path}")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def latest_eval_report() -> Path:
    candidates = sorted(
        (path for path in (ROOT / "reports").glob("*/evals.json") if path.is_file()),
        key=lambda item: item.stat().st_mtime_ns,
    )
    offline_reports = [
        path
        for path in candidates
        if json.loads(path.read_text(encoding="utf-8")).get("mode") == "offline"
    ]
    if not offline_reports:
        raise ValueError("Evidência de eval offline ausente em reports/*/evals.json.")
    return offline_reports[-1]


def validate(
    build_path: Path,
    eval_path: Path,
    compose_path: Path,
    live_path: Path | None = None,
) -> dict[str, Any]:
    reports = {
        "build": read_report(build_path),
        "eval": read_report(eval_path),
        "compose": read_report(compose_path),
    }
    current = candidate_digest()
    issues: list[str] = []
    for name, report in reports.items():
        if report.get("candidate_sha256") != current:
            issues.append(f"hash do candidato diverge na evidência {name}")
    live_status = "not_provided"
    if live_path is not None:
        live = read_report(live_path)
        live_status = "passed"
        if live.get("candidate_sha256") != current:
            issues.append("hash do candidato diverge na evidência live")
            live_status = "failed"
        if live.get("mode") != "live" or live.get("live_authorized") is not True:
            issues.append("evidência live sem protocolo e autorização explícita")
            live_status = "failed"
        if live.get("rounds_completed") != 3 or live.get("passed") is not True:
            issues.append("evidência live incompleta ou reprovada")
            live_status = "failed"
        if live.get("dataset_sha256") != sha256(ROOT / "evals/cases.jsonl"):
            issues.append("hash do dataset diverge da evidência live")
            live_status = "failed"
        if live.get("catalog_sha256") != sha256(ROOT / "app/data/sessions.json"):
            issues.append("hash do catálogo diverge da evidência live")
            live_status = "failed"
    if reports["build"].get("status") != "passed":
        issues.append("build não aprovado")
    if reports["eval"].get("passed") is not True:
        issues.append("eval offline não aprovado")
    if reports["eval"].get("mode") != "offline":
        issues.append("a evidência de eval precisa ser offline")
    if reports["eval"].get("rounds_completed") != reports["eval"].get("rounds_requested"):
        issues.append("eval offline incompleto")
    if reports["compose"].get("status") != "passed":
        issues.append("smoke Compose não aprovado")

    if reports["eval"].get("dataset_sha256") != sha256(ROOT / "evals/cases.jsonl"):
        issues.append("hash do dataset diverge da evidência eval")
    if reports["eval"].get("catalog_sha256") != sha256(ROOT / "app/data/sessions.json"):
        issues.append("hash do catálogo diverge da evidência eval")

    artifacts = reports["build"].get("artifacts", {})
    if not artifacts:
        issues.append("hashes dos artefatos wheel/sdist ausentes")
    if not any(name.endswith(".whl") for name in artifacts) or not any(
        name.endswith(".tar.gz") for name in artifacts
    ):
        issues.append("evidência não inclui wheel e sdist")
    for name, expected_hash in artifacts.items():
        artifact = ROOT / "dist" / name
        if not artifact.is_file() or sha256(artifact) != expected_hash:
            issues.append(f"artefato ausente ou divergente: {name}")

    image_id = reports["compose"].get("image_id")
    if not isinstance(image_id, str) or not image_id.startswith("sha256:"):
        issues.append("digest da imagem Compose ausente")
    else:
        inspected = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", image_id],
            check=False,
            capture_output=True,
            text=True,
        )
        if inspected.returncode != 0 or inspected.stdout.strip() != image_id:
            issues.append("imagem local não corresponde ao digest evidenciado")

    return {
        "status": "passed" if not issues else "failed",
        "candidate_sha256": current,
        "evidence": {
            "build": str(build_path),
            "eval": str(eval_path),
            "compose": str(compose_path),
            "live": str(live_path) if live_path else None,
        },
        "live_status": live_status,
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", type=Path, default=ROOT / "reports/build.json")
    parser.add_argument("--eval", dest="eval_report", type=Path)
    parser.add_argument("--compose", type=Path, default=ROOT / "reports/compose.json")
    parser.add_argument("--live", type=Path)
    args = parser.parse_args()
    try:
        eval_path = args.eval_report or latest_eval_report()
        report = validate(args.build, eval_path, args.compose, args.live)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "issues": [str(exc)]}), file=sys.stderr)
        return 1
    destination = ROOT / "reports/release-check.json"
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
