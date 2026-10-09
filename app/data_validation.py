"""Validation for bundled event sessions and policy documents."""

from __future__ import annotations

import json
import re
from importlib.resources import files

FAQ_DOCUMENTS = {
    "acessibilidade.md",
    "alimentacao.md",
    "cancelamento.md",
    "conduta.md",
    "horarios.md",
    "inscricao.md",
    "reservas.md",
    "trilhas.md",
}
FAQ_METADATA = re.compile(r"^Versão: \d+ · Atualizado em \d{4}-\d{2}-\d{2}$")


def validate_faq_catalog() -> list[str]:
    root = files("app").joinpath("data/faq")
    documents = sorted(path.name for path in root.iterdir() if path.name.endswith(".md"))
    if set(documents) != FAQ_DOCUMENTS or len(documents) != 8:
        raise ValueError("O FAQ deve conter exatamente os oito documentos previstos.")
    for name in documents:
        lines = root.joinpath(name).read_text(encoding="utf-8").splitlines()
        if len(lines) < 3 or not lines[0].startswith("# "):
            raise ValueError(f"Documento FAQ sem título: {name}.")
        if FAQ_METADATA.fullmatch(lines[1]) is None:
            raise ValueError(f"Documento FAQ sem metadados de versão/data: {name}.")
    return documents


def load_session_seed() -> list[dict[str, object]]:
    """Load the versioned seed catalog used only to initialize an empty local database."""
    path = files("app").joinpath("data/sessions.json")
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
        raise ValueError("O seed de agenda precisa ser uma lista de registros.")
    return records
