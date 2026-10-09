"""Lexical FAQ retrieval over versioned Markdown documents."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from importlib.resources import files

from app.data_validation import FAQ_DOCUMENTS

STOPWORDS = {
    "a",
    "as",
    "o",
    "os",
    "de",
    "do",
    "da",
    "dos",
    "das",
    "e",
    "em",
    "no",
    "na",
    "para",
    "por",
    "que",
    "com",
    "um",
    "uma",
    "é",
    "ao",
    "às",
    "quais",
    "sao",
    "evento",
}


@dataclass(frozen=True)
class Chunk:
    document: str
    section: str
    text: str
    version: int = 1
    updated_at: str = "unknown"
    status: str = "current"
    trusted: bool = True
    valid_from: str | None = None
    valid_until: str | None = None
    conflict_group: str | None = None


class FAQSource(dict[str, object]):
    @property
    def document(self) -> str:
        return str(self["document"])


def _tokens(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return {word for word in re.findall(r"[a-z0-9]+", normalized) if word not in STOPWORDS}


def load_chunks() -> list[Chunk]:
    root = files("app").joinpath("data/faq")
    metadata_path = files("app").joinpath("data/faq_metadata.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    documents = metadata.get("documents", {})
    available = {path.name for path in root.iterdir() if path.name.endswith(".md")}
    if available != FAQ_DOCUMENTS:
        raise ValueError("O catálogo FAQ está incompleto ou contém documentos não reconhecidos.")
    chunks: list[Chunk] = []
    document_count = 0
    available = {path.name for path in root.iterdir() if path.name.endswith(".md")}
    if available != FAQ_DOCUMENTS:
        raise ValueError("O catálogo FAQ está incompleto ou contém documentos não reconhecidos.")
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if not path.name.endswith(".md"):
            continue
        document_count += 1
        document_metadata = documents[path.name]
        status = str(document_metadata["status"])
        if document_metadata.get("conflict_group"):
            status = "conflicted"
        elif (
            document_metadata.get("valid_from")
            and date.fromisoformat(str(document_metadata["valid_from"])) > date.today()
        ):
            status = "future"
        elif (
            document_metadata.get("valid_until")
            and date.fromisoformat(str(document_metadata["valid_until"])) < date.today()
        ):
            status = "superseded"
        section = path.name.removesuffix(".md")
        lines: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") and line.lstrip("#").startswith(" "):
                level = len(line) - len(line.lstrip("#"))
                if level == 1:
                    section = line[level:].strip()
                    lines = []
                    continue
                if lines:
                    chunks.append(
                        Chunk(
                            path.name,
                            section,
                            "\n".join(lines).strip(),
                            int(document_metadata["version"]),
                            str(document_metadata["updated_at"]),
                            status,
                            bool(document_metadata.get("trusted", True)),
                            str(document_metadata["valid_from"]),
                            (
                                str(document_metadata["valid_until"])
                                if document_metadata.get("valid_until")
                                else None
                            ),
                            (
                                str(document_metadata["conflict_group"])
                                if document_metadata.get("conflict_group")
                                else None
                            ),
                        )
                    )
                section = line[level:].strip()
                lines = [section]
            else:
                lines.append(line)
        if lines:
            chunks.append(
                Chunk(
                    path.name,
                    section,
                    "\n".join(lines).strip(),
                    int(document_metadata["version"]),
                    str(document_metadata["updated_at"]),
                    status,
                    bool(document_metadata.get("trusted", True)),
                    str(document_metadata["valid_from"]),
                    (
                        str(document_metadata["valid_until"])
                        if document_metadata.get("valid_until")
                        else None
                    ),
                    (
                        str(document_metadata["conflict_group"])
                        if document_metadata.get("conflict_group")
                        else None
                    ),
                )
            )
    if document_count < 8:
        raise ValueError("O FAQ precisa incluir pelo menos oito documentos Markdown.")
    return chunks


def search_faq(
    question: str, chunks: list[Chunk] | None = None, limit: int = 3
) -> dict[str, object]:
    query = _tokens(question)
    if not query:
        return {
            "answer": "Não localizei regra suficiente para responder com segurança.",
            "sources": [],
        }
    ranked = []
    for chunk in chunks if chunks is not None else load_chunks():
        if chunk.status != "current" or not chunk.trusted:
            continue
        terms = _tokens(chunk.text)
        score = len(query & terms) / len(query)
        if score >= 0.2:
            ranked.append((score, chunk))
    ranked.sort(key=lambda item: (-item[0], item[1].document, item[1].section))
    best_by_document: dict[str, tuple[float, Chunk]] = {}
    for score, chunk in ranked:
        current = best_by_document.get(chunk.document)
        if current is None:
            best_by_document[chunk.document] = (score, chunk)
    sources: list[FAQSource] = [
        FAQSource(
            document=chunk.document,
            section=chunk.section,
            excerpt=chunk.text[:700],
            score=round(score, 3),
            version=chunk.version,
            updated_at=chunk.updated_at,
            status=chunk.status,
            valid_from=chunk.valid_from,
            valid_until=chunk.valid_until,
            conflict_group=chunk.conflict_group,
        )
        for score, chunk in list(best_by_document.values())[:limit]
    ]
    if not sources:
        return {
            "answer": "Não localizei regra suficiente para responder com segurança.",
            "sources": [],
        }
    answer = (
        "Encontrei estes trechos relevantes no guia do evento. "
        "Confira as fontes antes de tomar uma decisão."
    )
    return {"answer": answer, "sources": sources}


def has_source(question: str, document: str) -> bool:
    result = search_faq(question)
    sources = result["sources"]
    return isinstance(sources, list) and any(
        isinstance(source, FAQSource) and source.document == document for source in sources
    )
