"""Lexical FAQ retrieval over versioned Markdown documents."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
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


class FAQSource(dict[str, str | float]):
    @property
    def document(self) -> str:
        return str(self["document"])


def _tokens(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return {word for word in re.findall(r"[a-z0-9]+", normalized) if word not in STOPWORDS}


def load_chunks() -> list[Chunk]:
    root = files("app").joinpath("data/faq")
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
                    chunks.append(Chunk(path.name, section, "\n".join(lines).strip()))
                section = line[level:].strip()
                lines = [section]
            else:
                lines.append(line)
        if lines:
            chunks.append(Chunk(path.name, section, "\n".join(lines).strip()))
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
