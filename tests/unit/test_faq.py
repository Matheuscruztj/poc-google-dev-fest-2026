from app.faq import Chunk, FAQSource, has_source, search_faq


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
