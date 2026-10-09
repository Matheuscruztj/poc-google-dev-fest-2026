from __future__ import annotations

from pathlib import Path

import pytest

from app.data_validation import FAQ_DOCUMENTS, validate_faq_catalog
from app.schedule import sessions_from_records


def test_catalog_has_twenty_valid_stable_sessions(records):
    sessions = sessions_from_records(records)
    assert len(sessions) == 20
    assert len({session.id for session in sessions}) == 20
    assert all(session.capacity > 0 for session in sessions)
    assert all(session.ends_at > session.starts_at for session in sessions)
    assert all(session.starts_at.utcoffset() is not None for session in sessions)
    assert len({session.starts_at.date() for session in sessions}) == 1


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data.pop(),
        lambda data: data.__setitem__(1, {**data[1], "id": data[0]["id"]}),
        lambda data: data[0].__setitem__("level", "inexistente"),
        lambda data: data[0].__setitem__("capacity", 0),
        lambda data: data[0].__setitem__("ends_at", data[0]["starts_at"]),
        lambda data: data[0].__setitem__("id", "inventado"),
    ],
)
def test_invalid_session_catalog_is_rejected(records, mutate):
    mutate(records)
    with pytest.raises(ValueError):
        sessions_from_records(records)


def test_faq_documents_are_complete_and_have_metadata():
    assert set(validate_faq_catalog()) == FAQ_DOCUMENTS


def test_adversarial_fixture_is_outside_bundled_faq_catalog():
    fixture = Path(__file__).parents[1] / "fixtures/adversarial/prompt_injection.md"
    assert fixture.is_file()
    assert fixture.name not in validate_faq_catalog()
