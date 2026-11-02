"""Module ② capacity status on the synthetic scenarios, including both cancellation paths."""

from event_ops_engine.capacity import SessionStatus, capacity_status, session_status
from event_ops_engine.clock import to_epoch
from event_ops_engine.engine import Engine
from event_ops_engine.facts import registration_facts
from tests.conftest import loaded, scenario


def value(status: SessionStatus, dim: str, val: str) -> tuple[int, int, int, int | None, bool]:
    for row in status.values:
        if (row.dim, row.value) == (dim, val):
            return row.filled, row.pending, row.gap, row.remaining, row.is_full
    raise AssertionError(f"{dim}={val} not reported")


def test_single_registrations_count_one_seat_each(engine: Engine) -> None:
    loaded(engine, "single")
    status = session_status(engine, "s1")
    # a seat awaiting payment is taken: remaining = capacity - confirmed - pending, gap likewise
    assert (status.capacity, status.filled, status.pending, status.remaining_seats) == (12, 4, 1, 7)
    assert not status.is_full
    assert value(status, "gender", "female") == (3, 1, 2, 2, False)
    assert value(status, "gender", "male") == (1, 0, 5, 5, False)
    assert value(status, "age_band", "20s") == (1, 1, 0, 10, False)
    assert value(status, "age_band", "30s") == (3, 0, 1, 9, False)


def test_cancelled_registration_gives_its_seat_back(engine: Engine) -> None:
    # r6 (male) was confirmed, then cancelled: it must not be in `filled`.
    loaded(engine, "single")
    assert ("r6",) not in engine.snapshot("confirmed")
    assert ("r6", "cancelled") in engine.snapshot("current_status")


def test_cancellation_by_status_event_updates_counts(engine: Engine) -> None:
    data = loaded(engine, "single")
    assert value(session_status(engine, "s1"), "gender", "male") == (1, 0, 5, 5, False)
    engine.insert("status_event", ("r4", to_epoch(data.now) - 60, "cancelled"))
    assert value(session_status(engine, "s1"), "gender", "male") == (0, 0, 6, 6, False)


def test_cancellation_by_retracting_facts_updates_counts(engine: Engine) -> None:
    data = loaded(engine, "single")
    engine.retract(registration_facts(data, data.registrations[0]))  # r1, female
    status = session_status(engine, "s1")
    assert value(status, "gender", "female") == (2, 1, 3, 3, False)
    assert status.filled == 3


def test_mixed_pair_splits_into_one_female_and_one_male(engine: Engine) -> None:
    loaded(engine, "pair-mixed")
    status = session_status(engine, "s2")
    assert status.filled == 4
    assert value(status, "gender", "female") == (3, 0, 3, 3, False)
    assert value(status, "gender", "male") == (1, 1, 4, 4, False)
    assert value(status, "age_band", "20s") == (2, 0, 0, 10, False)


def test_group_counts_people_and_unknown_party_is_flagged(engine: Engine) -> None:
    loaded(engine, "group")
    status = session_status(engine, "s3")
    assert status.filled == 7  # 5 known + 2 unknown people occupy seats
    assert value(status, "gender", "female") == (3, 0, 3, 3, False)
    assert value(status, "gender", "male") == (2, 0, 4, 4, False)
    assert [d.kind for d in status.needs_review] == ["ask"]
    assert status.needs_review[0].evidence == ("registration/r2", "unknown_party/r2")
    assert "r2" in status.needs_review[0].message


def test_full_session_and_full_target_are_reported(engine: Engine) -> None:
    loaded(engine, "ratio")
    status = session_status(engine, "s4b")
    assert status.is_full and status.remaining_seats == 0
    assert value(status, "gender", "female") == (6, 0, 0, 0, True)
    assert value(status, "gender", "male") == (3, 0, 3, 3, False)
    assert ("s4b", "gender", "male", 3) in engine.snapshot("imbalance")


def test_balanced_session_has_no_imbalance(engine: Engine) -> None:
    loaded(engine, "ratio")
    assert engine.rows("imbalance", "s4a") == []


def test_age_band_boundaries_land_in_the_right_bands(engine: Engine) -> None:
    loaded(engine, "boundary")
    status = session_status(engine, "s5a")
    assert value(status, "age_band", "20s") == (2, 0, 0, 10, False)
    assert value(status, "age_band", "30s") == (2, 0, 2, 10, False)
    assert status.filled == 6  # the 19-year-old (unknown band) still occupies a seat


def test_evidence_names_targets_and_contributing_registrations(engine: Engine) -> None:
    loaded(engine, "single")
    status = session_status(engine, "s1")
    female = next(v for v in status.values if (v.dim, v.value) == ("gender", "female"))
    assert female.evidence == (
        "target/s1/gender/female",
        "session_capacity/s1",
        "registration/r1",
        "registration/r2",
        "registration/r3",
    )


def test_capacity_status_without_engine_reports_every_session() -> None:
    statuses = capacity_status(scenario("ratio"))
    assert [s.session for s in statuses] == ["s4a", "s4b"]
