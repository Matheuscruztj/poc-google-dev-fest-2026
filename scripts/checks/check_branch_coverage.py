"""Enforce the G2 branch-coverage floor on domain modules."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

MODULES = (
    "app/schedule.py",
    "app/faq.py",
    "app/reservations.py",
    "app/storage.py",
)
MINIMUM_BRANCH_COVERAGE = 0.80


def main(path: Path) -> int:
    report: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    files = report.get("files", {})
    failures: list[str] = []
    results: list[dict[str, object]] = []
    for module in MODULES:
        summary = files.get(module, {}).get("summary", {})
        total = int(summary.get("num_branches", 0))
        covered = int(summary.get("covered_branches", 0))
        ratio = covered / total if total else 0.0
        results.append(
            {"module": module, "covered": covered, "total": total, "ratio": round(ratio, 4)}
        )
        if not total or ratio < MINIMUM_BRANCH_COVERAGE:
            failures.append(f"{module}: {covered}/{total} branches ({ratio:.1%})")
    print(json.dumps({"minimum": MINIMUM_BRANCH_COVERAGE, "modules": results}, indent=2))
    if failures:
        print("Branch coverage abaixo do mínimo: " + "; ".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1] if len(sys.argv) > 1 else "reports/coverage.json")))
