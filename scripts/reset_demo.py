"""Safely remove the synthetic local demo database."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO_ROOT = ROOT / "var"


def reset_demo(path_text: str | None = None) -> Path:
    mode = os.environ.get("EVENTOPS_MODE", "offline").strip().lower()
    if mode != "offline":
        raise ValueError("Reset permitido somente com EVENTOPS_MODE=offline.")
    candidate = Path(path_text or os.environ.get("EVENTOPS_DATABASE", "var/eventops.sqlite3"))
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    if candidate.is_symlink() or DEMO_ROOT.is_symlink():
        raise ValueError("Reset não segue links simbólicos.")
    resolved_root = DEMO_ROOT.resolve()
    resolved = candidate.resolve(strict=False)
    if resolved.parent != resolved_root or resolved.suffix not in {".sqlite", ".sqlite3"}:
        raise ValueError("Informe somente um arquivo SQLite diretamente dentro de var/.")
    if resolved.exists():
        if not resolved.is_file():
            raise ValueError("O destino do reset precisa ser um arquivo regular.")
        resolved.unlink()
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{resolved}{suffix}")
        if sidecar.is_symlink():
            raise ValueError("Reset não segue links simbólicos.")
        if sidecar.exists():
            sidecar.unlink()
    return resolved


if __name__ == "__main__":
    print(f"Banco local removido: {reset_demo()}")
