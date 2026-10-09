from datetime import datetime

from app.schedule import overlaps, sessions_from_records, suggest_schedule
from app.schemas import Session


def test_catalog_has_twenty_unique_tz_aware_sessions(records):
    values = sessions_from_records(records)
    assert len(values) == 20
    assert len({value.id for value in values}) == 20
    assert all(value.starts_at.utcoffset() is not None for value in values)


def test_adjacent_sessions_do_not_overlap(sessions):
    assert not overlaps(sessions[0], sessions[1])


def test_overlap_is_detected(sessions):
    assert overlaps(sessions[1], sessions[2])


def test_selects_three_non_conflicting_sessions_after_two_pm(sessions):
    after = datetime.fromisoformat("2026-11-07T14:00:00-03:00")
    result = suggest_schedule(sessions, track="IA", after=after)
    chosen = [Session.model_validate(item) for item in result["sessions"]]
    assert [item.id for item in chosen] == ["S11", "S13", "S18"]
    assert all(item.track == "IA" and item.starts_at >= after for item in chosen)
    assert chosen[0].ends_at <= chosen[1].starts_at
    assert chosen[1].ends_at <= chosen[2].starts_at


def test_fewer_results_explains_why(sessions):
    result = suggest_schedule(sessions, track="trilha-inexistente")
    assert result["sessions"] == []
    assert result["reason"]


def test_one_available_session_is_returned_when_three_were_requested(sessions):
    result = suggest_schedule([sessions[0]], limit=3)
    assert [item["id"] for item in result["sessions"]] == ["S01"]
    assert result["reason"]


def test_selector_handles_a_small_fixture_with_a_three_way_conflict(sessions):
    candidates = [
        Session(
            id=f"T{index}",
            title=f"Fixture {index}",
            track="QA",
            level="iniciante",
            starts_at=datetime.fromisoformat(start),
            ends_at=datetime.fromisoformat(end),
            capacity=5,
        )
        for index, start, end in [
            (1, "2026-11-07T10:00:00-03:00", "2026-11-07T11:00:00-03:00"),
            (2, "2026-11-07T10:30:00-03:00", "2026-11-07T11:30:00-03:00"),
            (3, "2026-11-07T11:00:00-03:00", "2026-11-07T12:00:00-03:00"),
        ]
    ]
    result = suggest_schedule(candidates, limit=3)
    assert [item["id"] for item in result["sessions"]] == ["T1", "T3"]
    assert result["reason"]


def test_selector_rejects_limit_outside_contract(sessions):
    import pytest

    with pytest.raises(ValueError, match="limite"):
        suggest_schedule(sessions, limit=4)


def test_catalog_rejects_mixed_event_dates(records):
    import pytest

    records[0]["starts_at"] = "2026-11-08T09:00:00-03:00"
    records[0]["ends_at"] = "2026-11-08T09:40:00-03:00"
    with pytest.raises(ValueError, match="data e fuso"):
        sessions_from_records(records)
