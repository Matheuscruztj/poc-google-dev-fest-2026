from datetime import date, timedelta
from json import dumps

import pytest

from app.faq import Chunk, FAQSource, has_source, load_chunks, search_faq


def test_known_question_returns_source_and_excerpt():
    result = search_faq(
        "Qual é o fuso dos horários?",
        [Chunk("horarios.md", "Data e fuso", "Horários no fuso de Fortaleza UTC−03:00.")],
    )
    assert result["sources"][0]["document"] == "horarios.md"
    assert result["sources"][0]["section"] == "Data e fuso"


def test_unrelated_question_abstains():
    result = search_faq(
        "qual é o preço das ações de uma empresa",
        [Chunk("reservas.md", "Como reservar", "Confirme explicitamente a vaga da palestra.")],
    )
    assert result["sources"] == []
    assert "Não localizei" in result["answer"]


def test_catalog_has_eight_markdown_sources():
    result = search_faq("acessibilidade", None)
    assert len({source["document"] for source in result["sources"]}) >= 1


def test_stopword_only_question_abstains():
    result = search_faq("de para com", [Chunk("x.md", "x", "reserva")])
    assert result["sources"] == []


def test_multiple_matching_sections_return_one_best_source_per_document():
    result = search_faq(
        "acessibilidade rampas",
        [
            Chunk("acessibilidade.md", "Entrada", "rampas acessibilidade entrada"),
            Chunk("acessibilidade.md", "Auditório", "acessibilidade rampas auditório"),
        ],
    )
    assert len(result["sources"]) == 1
    assert result["sources"][0]["section"] == "Auditório"


def test_has_source_checks_expected_document():
    assert has_source("Quais recursos de acessibilidade?", "acessibilidade.md")
    assert not has_source("Quais recursos de acessibilidade?", "reserva.md")


def test_faq_source_document_property_returns_document_name():
    source = FAQSource(document="faq.md", section="Seção", excerpt="texto", score=1.0)
    assert source.document == "faq.md"


@pytest.mark.parametrize(
    ("metadata", "expected_status"),
    [
        ({"conflict_group": "horarios"}, "conflicted"),
        ({"valid_from": (date.today() + timedelta(days=1)).isoformat()}, "future"),
        ({"valid_until": (date.today() - timedelta(days=1)).isoformat()}, "superseded"),
    ],
)
def test_load_chunks_marks_conflicted_and_out_of_date_documents(
    tmp_path, monkeypatch, metadata, expected_status
):
    import app.faq as faq

    documents_path = tmp_path / "faq"
    documents_path.mkdir()
    metadata_path = tmp_path / "faq_metadata.json"
    names = {"a.md", *(f"other-{number}.md" for number in range(7))}
    documents = {
        name: {
            "status": "current",
            "version": 2,
            "updated_at": "2026-01-01",
            "trusted": True,
            "valid_from": None,
            "valid_until": None,
            "conflict_group": None,
        }
        for name in names
    }
    documents["a.md"].update(metadata)
    metadata_path.write_text(dumps({"documents": documents}), encoding="utf-8")
    (documents_path / "a.md").write_text(
        "# Título\nTexto atual\n## Seção\nConteúdo", encoding="utf-8"
    )
    for name in names - {"a.md"}:
        (documents_path / name).write_text("Documento adicional", encoding="utf-8")

    class Resource:
        def joinpath(self, path):
            return documents_path if path == "data/faq" else metadata_path

    monkeypatch.setattr(faq, "files", lambda package: Resource())
    monkeypatch.setattr(faq, "FAQ_DOCUMENTS", names)

    chunks = load_chunks()
    target_chunks = [chunk for chunk in chunks if chunk.document == "a.md"]
    assert len(target_chunks) == 2
    assert all(chunk.status == expected_status for chunk in target_chunks)
    result = search_faq("Conteúdo atual", chunks)
    assert result["sources"] == []


def test_load_chunks_rejects_unknown_document_catalog(tmp_path, monkeypatch):
    import app.faq as faq

    documents_path = tmp_path / "faq"
    documents_path.mkdir()
    metadata_path = tmp_path / "faq_metadata.json"
    metadata_path.write_text('{"documents": {}}', encoding="utf-8")

    class Resource:
        def joinpath(self, path):
            return documents_path if path == "data/faq" else metadata_path

    monkeypatch.setattr(faq, "files", lambda package: Resource())
    with pytest.raises(ValueError, match="catálogo FAQ"):
        load_chunks()
