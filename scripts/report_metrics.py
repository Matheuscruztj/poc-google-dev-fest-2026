"""Aggregate measured latency and consumption without fabricating costs."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path
from typing import Any


def aggregate(report: dict[str, Any]) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for attempt in report.get("attempts", []):
        groups.setdefault(
            (
                str(attempt.get("architecture", report.get("mode", "unknown"))),
                str(attempt["category"]),
            ),
            [],
        ).append(attempt)
    output: dict[str, Any] = {
        "source_run_id": report.get("run_id"),
        "mode": report.get("mode"),
        "groups": [],
        "model_cost": None,
        "infrastructure_cost": None,
        "cost_status": "unknown_without_complete_usage_and_dated_price_table",
    }
    for (architecture, category), attempts in sorted(groups.items()):
        durations = [
            float(item["trace"]["duration_ms"])
            for item in attempts
            if isinstance(item.get("trace", {}).get("duration_ms"), (int, float))
        ]
        failures = sum(item.get("error") is not None for item in attempts)
        retries = sum(int(item.get("trace", {}).get("retries", 0) or 0) for item in attempts)
        tool_calls = sum(int(item.get("trace", {}).get("tool_calls", 0) or 0) for item in attempts)
        token_pairs = [
            (item["trace"].get("input_tokens"), item["trace"].get("output_tokens"))
            for item in attempts
        ]
        tokens_complete = all(left is not None and right is not None for left, right in token_pairs)
        row: dict[str, Any] = {
            "architecture": architecture,
            "category": category,
            "n": len(attempts),
            "success": len(attempts) - failures,
            "failure": failures,
            "timeout": sum(
                item.get("error") is not None and "timeout" in str(item["error"]).casefold()
                for item in attempts
            ),
            "retries": retries,
            "tool_calls": tool_calls,
            "latency_ms": {
                "n": len(durations),
                "median": statistics.median(durations) if durations else None,
                "min": min(durations) if durations else None,
                "max": max(durations) if durations else None,
                "p95": (
                    sorted(durations)[math.ceil(0.95 * len(durations)) - 1]
                    if len(durations) >= 100
                    else None
                ),
            },
            "tokens": (
                {
                    "input": sum(int(pair[0]) for pair in token_pairs),
                    "output": sum(int(pair[1]) for pair in token_pairs),
                }
                if tokens_complete
                else None
            ),
        }
        output["groups"].append(row)
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path, help="Arquivo evals.json ou comparison.json")
    args = parser.parse_args()
    data = json.loads(args.report.read_text(encoding="utf-8"))
    result = aggregate(data)
    destination = args.report.with_name("metrics.json")
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "written", "path": str(destination)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
