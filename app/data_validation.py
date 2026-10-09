"""Validation for bundled event sessions and policy documents."""

from __future__ import annotations

import json
import re
from datetime import date
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
FAQ_METADATA = re.compile(r"^Versão: (\d+) · Atualizado em (\d{4}-\d{2}-\d{2})$")


def validate_faq_catalog() -> list[str]:
    root = files("app").joinpath("data/faq")
    documents = sorted(path.name for path in root.iterdir() if path.name.endswith(".md"))
    if set(documents) != FAQ_DOCUMENTS or len(documents) != 8:
        raise ValueError("O FAQ deve conter exatamente os oito documentos previstos.")
    metadata = json.loads(
        files("app").joinpath("data/faq_metadata.json").read_text(encoding="utf-8")
    )
    metadata_documents = metadata.get("documents", {})
    if metadata.get("schema_version") != 1 or set(metadata_documents) != FAQ_DOCUMENTS:
        raise ValueError("Os metadados estruturados do FAQ não correspondem ao catálogo.")
    for name in documents:
        lines = root.joinpath(name).read_text(encoding="utf-8").splitlines()
        if len(lines) < 3 or not lines[0].startswith("# "):
            raise ValueError(f"Documento FAQ sem título: {name}.")
        markdown_metadata = FAQ_METADATA.fullmatch(lines[1])
        if markdown_metadata is None:
            raise ValueError(f"Documento FAQ sem metadados de versão/data: {name}.")
        record = metadata_documents[name]
        if (
            not isinstance(record.get("version"), int)
            or record["version"] < 1
            or record.get("status") not in {"current", "superseded", "conflicted"}
            or not isinstance(record.get("trusted"), bool)
            or (
                record.get("conflict_group") is not None
                and not isinstance(record.get("conflict_group"), str)
            )
        ):
            raise ValueError(f"Metadados estruturados inválidos no FAQ: {name}.")
        if (
            int(markdown_metadata.group(1)) != record["version"]
            or markdown_metadata.group(2) != record["updated_at"]
        ):
            raise ValueError(f"Metadados Markdown e JSON divergem no FAQ: {name}.")
        try:
            date.fromisoformat(record["updated_at"])
            date.fromisoformat(record["valid_from"])
            if record.get("valid_until") is not None:
                date.fromisoformat(record["valid_until"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Datas estruturadas inválidas no FAQ: {name}.") from exc
    return documents


def load_session_seed() -> list[dict[str, object]]:
    """Load the versioned seed catalog used only to initialize an empty local database."""
    path = files("app").joinpath("data/sessions.json")
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
        raise ValueError("O seed de agenda precisa ser uma lista de registros.")
    return records
