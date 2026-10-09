"""Disposable stdio MCP processes used to exercise timeout and crash handling."""

from __future__ import annotations

import os
import time


def main() -> None:
    kind = os.environ.get("EVENTOPS_MCP_HARNESS", "")
    if kind == "delay":
        time.sleep(30)
    elif kind == "crash":
        os._exit(23)
    raise SystemExit(2)


if __name__ == "__main__":
    main()
