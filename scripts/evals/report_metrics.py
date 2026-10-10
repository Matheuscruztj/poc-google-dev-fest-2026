"""Aggregate measured latency and consumption without fabricating costs."""

from __future__ import annotations

import argparse
import html
import json
import math
import statistics
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]


def price_table() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads((ROOT / "app/data/model_prices.json").read_text(encoding="utf-8")),
    )


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
    prices = price_table()
    output: dict[str, Any] = {
        "source_run_id": report.get("run_id"),
        "mode": report.get("mode"),
        "groups": [],
        "model_cost_usd": None,
        "infrastructure_cost": None,
        "price_table_version": prices["version"],
        "cost_status": "unknown",
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
        traces = [item.get("trace", {}) for item in attempts]
        known_input = [
            trace["input_tokens"] for trace in traces if trace.get("input_tokens") is not None
        ]
        known_output = [
            trace["output_tokens"] for trace in traces if trace.get("output_tokens") is not None
        ]
        modes = {
            str(trace.get("mode", report.get("mode", "unknown"))).split(":", 1)[0]
            for trace in traces
        }
        model_cost: float | None = None
        cost_status = "unknown_usage_or_price"
        if modes == {"offline"}:
            model_cost, cost_status = 0.0, "zero_api_cost"
        elif modes == {"local"}:
            cost_status = "local_compute_not_priced"
        elif len(modes) == 1:
            provider = next(iter(modes))
            rate = prices["providers"].get(provider, {})
            input_rate, output_rate = rate.get("input_per_million"), rate.get("output_per_million")
            complete = len(known_input) == len(attempts) and len(known_output) == len(attempts)
            if (
                complete
                and isinstance(input_rate, (int, float))
                and isinstance(output_rate, (int, float))
            ):
                model_cost = (
                    sum(known_input) * float(input_rate) + sum(known_output) * float(output_rate)
                ) / 1_000_000
                cost_status = "estimated_from_dated_price_table"
            else:
                cost_status = str(rate.get("billing", "unknown_usage_or_price"))
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
            "provider_calls": sum(int(trace.get("provider_calls", 0) or 0) for trace in traces),
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
            "tokens": {
                "input": sum(int(value) for value in known_input) if known_input else None,
                "output": sum(int(value) for value in known_output) if known_output else None,
                "input_measured_attempts": len(known_input),
                "output_measured_attempts": len(known_output),
                "total_attempts": len(attempts),
                "status": (
                    "complete"
                    if len(known_input) == len(attempts) and len(known_output) == len(attempts)
                    else "partial"
                    if known_input or known_output
                    else "unknown"
                ),
            },
            "model_cost_usd": model_cost,
            "cost_status": cost_status,
        }
        output["groups"].append(row)
    if output["groups"] and all(row["model_cost_usd"] is not None for row in output["groups"]):
        output["model_cost_usd"] = sum(float(row["model_cost_usd"]) for row in output["groups"])
        output["cost_status"] = "estimated_or_zero_from_dated_price_table"
    return output


def render_dashboard(result: dict[str, Any]) -> str:
    rows = []
    for item in result["groups"]:
        tokens = item["tokens"]
        token_text = f"in {tokens['input']} / out {tokens['output']} ({tokens['status']})"
        cost = (
            f"${item['model_cost_usd']:.6f}"
            if item["model_cost_usd"] is not None
            else "indisponível"
        )
        rows.append(
            "<tr>"
            f"<td>{html.escape(item['architecture'])}</td>"
            f"<td>{html.escape(item['category'])}</td>"
            f"<td>{item['success']} / {item['n']}</td>"
            f"<td>{item['latency_ms']['median']}</td>"
            f"<td>{item['latency_ms']['p95']}</td>"
            f"<td>{html.escape(token_text)}</td>"
            f"<td>{cost}<br><small>{html.escape(item['cost_status'])}</small></td>"
            "</tr>"
        )
    return (
        "<!doctype html><html lang='pt-BR'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Métricas locais EventOps</title>"
        "<style>body{font:14px system-ui;margin:2rem;color:#17212b}"
        "table{border-collapse:collapse;width:100%}"
        "th,td{padding:.65rem;border-bottom:1px solid #ddd;text-align:left}"
        "small{color:#667}</style><h1>Métricas da execução local</h1>"
        f"<p>Execução {html.escape(str(result.get('source_run_id')))} · "
        f"preços {html.escape(str(result['price_table_version']))}</p>"
        "<table><thead><tr><th>Arquitetura</th><th>Tarefa</th><th>Sucesso</th>"
        "<th>Duração mediana ms</th><th>p95 ms</th><th>Tokens</th><th>Custo modelo</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></html>\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path, help="Arquivo evals.json ou comparison.json")
    args = parser.parse_args()
    data = json.loads(args.report.read_text(encoding="utf-8"))
    result = aggregate(data)
    destination = args.report.with_name("metrics.json")
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    dashboard = args.report.with_name("metrics.html")
    dashboard.write_text(render_dashboard(result), encoding="utf-8")
    print(json.dumps({"status": "written", "path": str(destination), "dashboard": str(dashboard)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
