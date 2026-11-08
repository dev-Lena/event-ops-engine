"""Headcount conversion: registrations become attendees with attributes (design.md 4)."""

from event_ops_engine.facts import attendee_id, evidence_id, registration_facts, scenario_facts
from tests.conftest import scenario


def rows(facts: dict[str, list[tuple[object, ...]]], relation: str) -> list[tuple[object, ...]]:
    return facts.get(relation, [])


def test_single_registration_is_one_attendee_with_registrant_gender() -> None:
    data = scenario("single")
    facts = registration_facts(data, data.registrations[0]).rows
    assert rows(facts, "attendee") == [("r1", "r1#1")]
    assert ("r1#1", "gender", "female") in rows(facts, "given_attr")
    assert ("r1#1", "age_band", "20s") in rows(facts, "given_attr")


def test_mixed_pair_is_one_female_and_one_male() -> None:
    data = scenario("pair-mixed")
    facts = registration_facts(data, data.registrations[0]).rows
    genders = sorted(v for a, d, v in rows(facts, "given_attr") if d == "gender")
    assert genders == ["female", "male"]
    assert len(rows(facts, "attendee")) == 2


def test_same_gender_pair_counts_two_of_that_gender() -> None:
    data = scenario("pair-mixed")
    facts = registration_facts(data, data.registrations[1]).rows
    genders = [v for a, d, v in rows(facts, "given_attr") if d == "gender"]
    assert genders == ["female", "female"]


def test_group_expands_to_one_attendee_per_member() -> None:
    data = scenario("group")
    facts = registration_facts(data, data.registrations[0]).rows
    assert len(rows(facts, "attendee")) == 5
    assert rows(facts, "unknown_party") == []


def test_unknown_party_gets_unknown_attributes_and_a_review_fact() -> None:
    data = scenario("group")
    facts = registration_facts(data, data.registrations[1]).rows
    assert rows(facts, "unknown_party") == [("r2", 2)]
    assert len(rows(facts, "attendee")) == 2
    values = {(d, v) for a, d, v in rows(facts, "given_attr")}
    assert values == {("gender", "unknown"), ("age_band", "unknown")}


def test_status_events_become_epoch_rows() -> None:
    data = scenario("single")
    facts = registration_facts(data, data.registrations[5]).rows
    statuses = [row[2] for row in rows(facts, "status_event")]
    assert statuses == ["confirmed", "cancelled"]
    assert all(isinstance(row[1], int) for row in rows(facts, "status_event"))


def test_scenario_facts_carry_session_targets_policy_and_now() -> None:
    facts = scenario_facts(scenario("single")).rows
    assert rows(facts, "session_capacity") == [("s1", 12)]
    assert rows(facts, "days_left") == [("s1", 14)]
    assert ("s1", "gender", "female", 6, 6) in rows(facts, "target")
    assert ("s1", "age_band", "20s", 2, 12) in rows(facts, "target")
    assert rows(facts, "ratio_target") == [("s1", "gender", "female", "male", 1)]
    assert set(rows(facts, "policy")) == {
        ("s1", "lead_days", 7),
        ("s1", "trend_min_per_week", 3),
        ("s1", "promotion_cutoff_hours", 2),
    }
    assert len(rows(facts, "now")) == 1


def test_ids_are_stable() -> None:
    assert attendee_id("r7", 0) == "r7#1"
    assert evidence_id("target", "s1", "gender", "female") == "target/s1/gender/female"


def test_session_overrides_and_start_time_shape_the_cutoff_facts() -> None:
    from datetime import datetime, time

    base = scenario("single")  # s1 on 2026-11-21, no start time
    facts = scenario_facts(base).rows
    seoul_midnight = datetime.fromisoformat("2026-11-21T00:00:00+09:00").timestamp()
    assert rows(facts, "earliest_cutoff_ts") == [("s1", int(seoul_midnight) - 2 * 3600)]
    assert rows(facts, "promotion_cutoff_ts") == []

    session = base.sessions[0].model_copy(
        update={"start_time": time(19, 30), "lead_days": 0, "promotion_cutoff_hours": 0}
    )
    facts = scenario_facts(base.model_copy(update={"sessions": (session,)})).rows
    start = datetime.fromisoformat("2026-11-21T19:30:00+09:00").timestamp()
    assert rows(facts, "promotion_cutoff_ts") == [("s1", int(start))]  # 0 hours is kept
    assert ("s1", "lead_days", 0) in rows(facts, "policy")
    assert rows(facts, "earliest_cutoff_ts") == []
