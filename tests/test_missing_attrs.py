"""A seat holder with no gender or no choice answer is put in front of the operator (#103).

Both used to count as `unknown`: the person fell out of every target, the shortfall grew by
one, and nothing said why. They still load and still count that way for this release; the
only change is the review.
"""

from pathlib import Path
from typing import Any

import pytest

from event_ops_engine.capacity import capacity_status
from event_ops_engine.cli import report, report_json, run_report
from event_ops_engine.decision import Decision
from event_ops_engine.facts import triage_facts
from event_ops_engine.harness import run_triage
from event_ops_engine.interpreter import FakeInterpreter
from event_ops_engine.loader import load_policy, load_scenario, load_triage_scenario
from event_ops_engine.model import Scenario
from tests.conftest import REPO, SCENARIOS

HYBRID = REPO / "policy" / "events" / "synthetic-hybrid.yaml"
"""Choices: `mode` per registration, `region` per member."""

FULL = {"gender": "female", "birth_year": 1996, "attrs": {"region": "seoul"}}


def scenario(*registrations: dict[str, Any]) -> Scenario:
    return Scenario.model_validate(
        {
            "policy": load_policy(HYBRID),
            "now": "2026-11-07T10:00:00+09:00",
            "sessions": [{"id": "s1", "date": "2026-11-12"}],
            "registrations": [
                {
                    "session": "s1",
                    "attrs": {"mode": "offline"},
                    "status_events": [{"at": "2026-11-01T10:00:00+09:00", "status": "confirmed"}],
                    **registration,
                }
                for registration in registrations
            ],
        }
    )


def reviews(data: Scenario) -> list[Decision]:
    (status,) = capacity_status(data)
    return list(status.needs_review)


@pytest.mark.parametrize("member", [{"gender": "unknown"}, {}], ids=["written", "left out"])
def test_a_seat_holder_without_gender_is_reviewed(member: dict[str, str]) -> None:
    blank = {**FULL, **member} if member else {k: v for k, v in FULL.items() if k != "gender"}
    (review,) = reviews(scenario({"id": "r1", "members": [FULL]}, {"id": "r2", "members": [blank]}))
    assert review.kind == "ask" and review.reasons == ("missing_gender",)
    assert review.evidence == ("registration/r2", "given_attr/r2#1/gender")
    assert review.message.startswith("신청 r2: 성별이 없는 참가자가 있습니다")


def test_a_member_without_a_choice_answer_is_reviewed() -> None:
    blank = {"gender": "male", "birth_year": 1993}
    (review,) = reviews(scenario({"id": "r1", "members": [FULL, blank]}))
    assert review.reasons == ("missing_choice",)
    assert review.evidence == ("registration/r1", "given_attr/r1#2/region")
    assert "선택 속성(region) 답이 없습니다" in review.message


def test_a_registration_level_answer_is_reviewed_once_however_many_members() -> None:
    (review,) = reviews(scenario({"id": "r1", "attrs": {}, "members": [FULL, FULL]}))
    assert review.reasons == ("missing_choice",) and "선택 속성(mode)" in review.message
    assert review.evidence == (
        "registration/r1",
        "given_attr/r1#1/mode",
        "given_attr/r1#2/mode",
    )


def test_blank_gender_and_blank_answers_are_two_reviews_naming_every_attribute() -> None:
    found = reviews(scenario({"id": "r1", "attrs": {}, "members": [{"birth_year": 1996}]}))
    assert sorted(review.reasons for review in found) == [("missing_choice",), ("missing_gender",)]
    choice = next(review for review in found if review.reasons == ("missing_choice",))
    assert "선택 속성(mode · region)" in choice.message


@pytest.mark.parametrize("status", ["applied", "cancelled", "refunded"])
def test_only_seat_holders_are_reviewed(status: str) -> None:
    events = [{"at": "2026-11-01T10:00:00+09:00", "status": status}]
    assert not reviews(scenario({"id": "r1", "members": [{}], "status_events": events}))


def test_a_seat_awaiting_payment_is_reviewed_too() -> None:
    events = [{"at": "2026-11-01T10:00:00+09:00", "status": "pending_payment"}]
    blank = {"birth_year": 1990, "attrs": {"region": "seoul"}}
    (review,) = reviews(scenario({"id": "r1", "members": [FULL, blank], "status_events": events}))
    assert review.reasons == ("missing_gender",)


def test_unknown_composition_keeps_its_own_review_for_the_per_person_blanks() -> None:
    """`unknown_party` already asks who is coming; only the registration-level answer is new."""
    found = reviews(scenario({"id": "r1", "party_size": 2}))
    assert [review.reasons for review in found] == [("unknown_party",)]
    found = reviews(scenario({"id": "r1", "party_size": 2, "attrs": {}}))
    assert sorted(review.reasons for review in found) == [("missing_choice",), ("unknown_party",)]
    choice = next(review for review in found if review.reasons == ("missing_choice",))
    assert "선택 속성(mode)" in choice.message


def test_a_pair_given_by_type_only_has_no_per_person_answers() -> None:
    (review,) = reviews(scenario({"id": "r1", "pair": "mixed_pair"}))
    assert review.reasons == ("missing_choice",) and "선택 속성(region)" in review.message


def test_the_blank_still_counts_as_before_for_this_release() -> None:
    """Grace period: the person holds a seat and stays out of the targets, exactly as before."""
    data = scenario({"id": "r1", "members": [FULL]}, {"id": "r2", "members": [{}]})
    (status,) = capacity_status(data)
    assert status.filled == 2
    seoul = next(v for v in status.values if (v.dim, v.value) == ("region", "seoul"))
    assert seoul.filled == 1 and seoul.gap == 3


def test_the_shipped_hybrid_scenario_now_names_its_blank_registration() -> None:
    path = SCENARIOS / "hybrid.yaml"
    line = "  확인 요청: 신청 r5: 선택 속성(mode · region) 답이 없습니다."
    assert any(text.startswith(line) for text in report(path))
    (session,) = report_json(run_report(path))["sessions"]
    assert [review["reasons"] for review in session["needs_review"]] == [["missing_choice"]]


def test_the_triage_path_loads_the_same_rules_with_a_choice_policy(tmp_path: Path) -> None:
    """Triage reuses the capacity rules, so `choice_dim` has to load there as well."""
    source = (SCENARIOS / "triage" / "seat-full.yaml").read_text(encoding="utf-8")
    old = "policy: ../../../../policy/events/synthetic-example.yaml"
    assert old in source
    path = tmp_path / "seat.yaml"
    path.write_text(source.replace(old, f"policy: '{HYBRID}'"), encoding="utf-8")
    scenario_with_choices = load_triage_scenario(path)
    assert ("mode", "registration") in triage_facts(scenario_with_choices).rows["choice_dim"]
    run_triage(scenario_with_choices, FakeInterpreter())  # the engine accepts the facts


OTHERS = sorted(path for path in SCENARIOS.glob("*.yaml") if path.stem != "hybrid")


@pytest.mark.parametrize("path", OTHERS, ids=[p.stem for p in OTHERS])
def test_no_other_shipped_scenario_gains_a_review(path: Path) -> None:
    for status in capacity_status(load_scenario(path)):
        reasons = {reason for review in status.needs_review for reason in review.reasons}
        assert not reasons & {"missing_gender", "missing_choice"}
