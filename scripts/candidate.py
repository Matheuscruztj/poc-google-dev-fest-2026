"""Stable digest of source inputs used to bind local evidence to a candidate."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def candidate_digest() -> str:
    paths = subprocess.run(
        ["git", "ls-files", "-z", "-co", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout.split(b"\0")
    digest = hashlib.sha256()
    for raw_path in sorted(item for item in paths if item):
        path = Path(raw_path.decode("utf-8"))
        absolute = ROOT / path
        if not absolute.is_file():
            continue
        digest.update(path.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(absolute.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
