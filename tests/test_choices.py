"""Fixed-choice attributes (#31): region per member, mode per registration."""

from typing import Any

import pytest
from pydantic import ValidationError

from event_ops_engine.capacity import capacity_status
from event_ops_engine.facts import dimension_values, scenario_facts
from event_ops_engine.loader import load_policy
from event_ops_engine.model import EventPolicy, Scenario
from event_ops_engine.promotion import promotion_decisions
from tests.conftest import REPO, scenario

HYBRID = REPO / "policy" / "events" / "synthetic-hybrid.yaml"


def by_value(data: Scenario) -> dict[tuple[str, str], tuple[int, int, int]]:
    (status,) = capacity_status(data)
    return {(v.dim, v.value): (v.filled, v.pending, v.gap) for v in status.values}


def test_choices_are_counted_like_any_other_attribute() -> None:
    data = scenario("hybrid")
    counts = by_value(data)
    # r1 is a pair with mode on the registration: both attendees count as offline.
    assert counts[("mode", "offline")] == (3, 1, 4)
    assert counts[("mode", "online")] == (2, 0, 0)
    assert counts[("region", "seoul")] == (3, 0, 1)
    (status,) = capacity_status(data)
    assert status.filled == 6  # r5 answered nothing: in the headcount, in no choice value
    recommended = {(d.dim, d.value): d.need for d in promotion_decisions(data)}
    assert recommended == {("mode", "offline"): 4, ("region", "seoul"): 1}


def test_unanswered_choices_become_unknown_facts() -> None:
    rows = scenario_facts(scenario("hybrid")).rows["given_attr"]
    assert ("r5#1", "mode", "unknown") in rows and ("r5#1", "region", "unknown") in rows
    assert ("r1#2", "mode", "offline") in rows and ("r1#2", "region", "gyeonggi") in rows


def test_questions_may_point_at_choice_values() -> None:
    assert ("mode", "online") in dimension_values(load_policy(HYBRID))


def policy_with(**changes: Any) -> dict[str, Any]:
    raw = load_policy(HYBRID).model_dump(by_alias=True)
    for key, value in changes.items():
        section, field = key.split("__")
        raw[section][field] = value
    return raw


@pytest.mark.parametrize(
    "changes",
    [
        {"defaults__targets": {"mode": {"hybrid": {"lo": 1}}}},  # undeclared value
        {"defaults__targets": {"seat_type": {"vip": {"lo": 1}}}},  # undeclared attribute
        {"defaults__ratios": [{"dim": "mode", "values": ["offline", "remote"]}]},
        {"dimensions__choices": {"gender": {"values": ["x"]}}},  # built-in name
        {"dimensions__choices": {"mode": {"values": ["online", "online"]}}},
        {"dimensions__choices": {"mode": {"values": ["unknown"]}}},
    ],
)
def test_policy_rejects_targets_and_choices_that_could_never_be_met(
    changes: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        EventPolicy.model_validate(policy_with(**changes))


def test_the_old_silent_gap_is_now_an_error() -> None:
    """Before #31 a target on an undeclared attribute loaded and showed a gap forever."""
    raw = load_policy(REPO / "policy" / "events" / "synthetic-example.yaml").model_dump(
        by_alias=True
    )
    raw["defaults"]["targets"]["mode"] = {"online": {"lo": 2}}
    with pytest.raises(ValidationError, match="undeclared"):
        EventPolicy.model_validate(raw)


def scenario_with(registration: dict[str, Any], session: dict[str, Any] | None = None) -> None:
    Scenario.model_validate(
        {
            "policy": load_policy(HYBRID).model_dump(by_alias=True),
            "now": "2026-11-07T10:00:00+09:00",
            "sessions": [{"id": "s1", "date": "2026-11-12", **(session or {})}],
            "registrations": [
                {
                    "id": "r1",
                    "session": "s1",
                    "status_events": [{"at": "2026-11-01T10:00:00+09:00", "status": "confirmed"}],
                    **registration,
                }
            ],
        }
    )


@pytest.mark.parametrize(
    ("registration", "session", "problem"),
    [
        ({"attrs": {"mode": "hybrid"}, "members": [{}]}, None, "not one of"),
        ({"attrs": {"region": "seoul"}, "members": [{}]}, None, "per-registration"),
        ({"members": [{"attrs": {"mode": "online"}}]}, None, "per-member"),
        ({"members": [{"attrs": {"name": "free text"}}]}, None, "per-member"),
        ({"members": [{}]}, {"targets": {"mode": {"remote": {"lo": 1}}}}, "session s1"),
    ],
)
def test_answers_must_come_from_the_declared_lists(
    registration: dict[str, Any], session: dict[str, Any] | None, problem: str
) -> None:
    with pytest.raises(ValidationError, match=problem):
        scenario_with(registration, session)
