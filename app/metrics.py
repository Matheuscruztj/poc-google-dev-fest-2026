"""Sanitized JSONL traces for synthetic demonstration requests."""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

LOGGER = logging.getLogger("eventops.trace")
REDACTIONS = [
    re.compile(r"(?i)(AIza[0-9A-Za-z_-]{20,})"),
    re.compile(r"(?i)(confirmation_token[\"']?\s*[:=]\s*[\"']?)[^\s,}\"']+"),
]


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if key.casefold() in {"google_api_key", "api_key", "confirmation_token"}
            else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        result = value
        for pattern in REDACTIONS:
            result = pattern.sub(
                lambda match: (match.group(1) if match.lastindex else "") + "[REDACTED]", result
            )
        return result
    return value


class Trace:
    def __init__(self, mode: str, model: str, dataset_version: str = "none") -> None:
        self.request_id = str(uuid4())
        self.mode = mode
        self.model = model
        self.dataset_version = dataset_version
        self.started = time.monotonic()
        self.calls = 0
        self.retries = 0
        self.tools: list[str] = []
        self.input_tokens: int | None = None
        self.output_tokens: int | None = None

    def record_tool(self, name: str) -> None:
        self.calls += 1
        self.tools.append(name)

    def finish(
        self, status: str, *, raw_output: str | None, validated: bool, fallback: bool
    ) -> dict[str, Any]:
        event = {
            "request_id": self.request_id,
            "mode": self.mode,
            "model": self.model,
            "dataset_version": self.dataset_version,
            "duration_ms": round((time.monotonic() - self.started) * 1000, 2),
            "tool_calls": self.calls,
            "retries": self.retries,
            "tools": self.tools,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "status": status,
            "raw_output": raw_output,
            "validated": validated,
            "fallback": fallback,
            "reservation_writes": 0,
        }
        logged_event = {**event, "raw_output": "[OMITTED]" if raw_output is not None else None}
        LOGGER.info(json.dumps(redact(logged_event), ensure_ascii=False))
        return cast(dict[str, Any], redact(event))


def configure_file_logging(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    target = str(path.resolve())
    if any(getattr(handler, "baseFilename", None) == target for handler in LOGGER.handlers):
        return
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    LOGGER.setLevel(logging.INFO)
    LOGGER.addHandler(handler)
