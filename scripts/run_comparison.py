"""Paired offline comparison of single and multi-agent architectures."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent import PROMPT_VERSION, make_agent  # noqa: E402
from app.agents.coordinator import COORDINATOR_PROMPT_VERSION, CoordinatorAgent  # noqa: E402
from app.data_validation import load_session_seed  # noqa: E402
from app.evaluators import evaluate_case, load_cases, run_case  # noqa: E402
from app.schemas import Session  # noqa: E402
from evals.harness import multi_failure_result, single_agent_for_case  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def run(rounds: int) -> int:
    if not 1 <= rounds <= 3:
        raise ValueError("--rounds deve estar entre 1 e 3.")
    dataset = ROOT / "evals/cases.jsonl"
    cases = load_cases(dataset)
    sessions = [Session.model_validate(item) for item in load_session_seed()]
    single = make_agent(sessions, "offline", "offline", None)
    multi = CoordinatorAgent(sessions, mode="offline", model="offline", use_mcp=True)
    report: dict[str, Any] = {
        "run_id": datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8],
        "created_at": datetime.now(UTC).isoformat(),
        "mode": "offline-paired",
        "dataset_sha256": digest(dataset),
        "catalog_sha256": digest(ROOT / "app/data/sessions.json"),
        "architectures": {
            "single": {"prompt_version": PROMPT_VERSION, "transport": "internal"},
            "multi": {"prompt_version": COORDINATOR_PROMPT_VERSION, "transport": "MCP stdio"},
        },
        "rounds_requested": rounds,
        "attempts": [],
    }
    for round_number in range(1, rounds + 1):
        for case in cases:
            for name, agent in (("single", single), ("multi", multi)):
                if name == "single":
                    case_agent = single_agent_for_case(sessions, case, single)
                    result = await run_case(case_agent, case)
                elif case.get("category") in {"tool_failure", "model_failure"}:
                    result = multi_failure_result(str(case["category"]))
                else:
                    result = await run_case(agent, case)
                verdict = evaluate_case(case, result)
                report["attempts"].append(
                    {
                        "round": round_number,
                        "case_id": case["id"],
                        "category": case["category"],
                        "architecture": name,
                        "answer": result.answer,
                        "session_ids": result.session_ids,
                        "sources": result.sources,
                        "reservation_proposal": result.reservation_proposal,
                        "error": result.error,
                        "trace": result.trace,
                        "evaluation": verdict,
                    }
                )
    report["summary"] = [
        {
            "round": round_number,
            "architecture": architecture,
            "category": category,
            "passed": sum(
                item["evaluation"]["passed"]
                for item in report["attempts"]
                if item["round"] == round_number
                and item["architecture"] == architecture
                and item["category"] == category
            ),
            "total": sum(
                1
                for item in report["attempts"]
                if item["round"] == round_number
                and item["architecture"] == architecture
                and item["category"] == category
            ),
        }
        for round_number in range(1, rounds + 1)
        for architecture in ("single", "multi")
        for category in sorted({case["category"] for case in cases})
    ]
    report["human_review_required"] = True
    report["passed"] = all(item["evaluation"]["passed"] for item in report["attempts"])
    out_dir = ROOT / "reports" / report["run_id"]
    out_dir.mkdir(parents=True, exist_ok=False)
    (out_dir / "comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        f"# Comparação pareada — {report['run_id']}",
        "",
        "Modo offline; single usa ferramentas internas e multi usa MCP stdio.",
        "A diferença de transporte faz parte do experimento pareado.",
        "Alegações livres exigem revisão humana; resultado offline não aprova qualidade live G4.",
        "",
        "| Rodada | Arquitetura | Categoria | Aprovados | Total |",
        "|---:|---|---|---:|---:|",
    ]
    lines.extend(
        "| {round} | {architecture} | {category} | {passed} | {total} |".format(**item)
        for item in report["summary"]
        if item["total"]
    )
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        json.dumps({"run_id": report["run_id"], "passed": report["passed"], "report": str(out_dir)})
    )
    return 0 if report["passed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=1)
    args = parser.parse_args()
    try:
        return asyncio.run(run(args.rounds))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
