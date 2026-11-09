"""Combination targets (#32): one gender plus an age range, counted as dimension `combo`."""

from typing import Any

import pytest
from pydantic import ValidationError

from event_ops_engine.capacity import capacity_status
from event_ops_engine.cli import report, report_json, run_report
from event_ops_engine.facts import scenario_facts
from event_ops_engine.model import Combo, EventPolicy, Registration, Scenario
from event_ops_engine.policy import resolve_targets
from event_ops_engine.promotion import promotion_decisions
from tests.conftest import SCENARIOS, scenario

BASE: dict[str, Any] = {
    "event": "e",
    "defaults": {
        "capacity": 10,
        "combos": {"f25_29": {"gender": "female", "age": [25, 29]}},
        "targets": {"combo": {"f25_29": {"lo": 2}}},
    },
    "promotion": {"lead_days": 7, "trend_min_per_week": 3},
}
NOW = "2026-11-07T10:00:00+09:00"


def policy(**defaults: Any) -> EventPolicy:
    return EventPolicy.model_validate({**BASE, "defaults": {**BASE["defaults"], **defaults}})


def with_session(**session: Any) -> Scenario:
    return Scenario.model_validate(
        {"policy": BASE, "now": NOW, "sessions": [{"id": "s", "date": "2026-11-14", **session}]}
    )


@pytest.mark.parametrize(
    "combo",
    [
        {"gender": "unknown", "age": [25, 29]},
        {"gender": "female", "age": [30, 25]},
        {"gender": "female", "age": [-1, 5]},
        {"gender": "female", "age": [25, 29], "region": "seoul"},  # gender and age only
    ],
)
def test_a_combination_is_a_known_gender_and_an_ordered_age_range(combo: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Combo.model_validate(combo)


@pytest.mark.parametrize(
    "defaults",
    [
        # Overlapping ranges of one gender would count a 29-year-old woman twice in a sum.
        {"combos": {**BASE["defaults"]["combos"], "f29_33": {"gender": "female", "age": [29, 33]}}},
        {"combos": {"unknown": {"gender": "female", "age": [25, 29]}}, "targets": {}},
        {"targets": {"combo": {"f30_34": {"lo": 1}}}},  # target on an undefined combination
    ],
)
def test_combinations_that_cannot_be_counted_cleanly_are_rejected(defaults: Any) -> None:
    with pytest.raises(ValidationError):
        policy(**defaults)


def test_ratios_cannot_name_combinations_because_forms_close_by_gender() -> None:
    combos = {**BASE["defaults"]["combos"], "f30_34": {"gender": "female", "age": [30, 34]}}
    ratio = {"dim": "combo", "values": ["f25_29", "f30_34"]}
    with pytest.raises(ValidationError, match="can't name combinations"):
        policy(combos=combos, ratios=[ratio])


def test_a_combination_must_use_a_gender_the_policy_tracks() -> None:
    data = {**BASE, "dimensions": {"gender": {"values": ["female"]}}}
    data["defaults"] = {
        **BASE["defaults"],
        "combos": {"m25_29": {"gender": "male", "age": [25, 29]}},
    }
    data["defaults"]["targets"] = {}
    with pytest.raises(ValidationError, match="gender the policy lacks"):
        EventPolicy.model_validate(data)


def test_a_birth_year_after_the_session_year_is_flagged_like_a_missing_one() -> None:
    data = with_session().model_copy(
        update={
            "registrations": (
                Registration.model_validate(
                    {
                        "id": "r",
                        "session": "s",
                        "members": [{"gender": "female", "birth_year": 2027}],
                        "status_events": [{"at": NOW, "status": "confirmed"}],
                    }
                ),
            )
        }
    )
    facts = scenario_facts(data).rows
    assert facts["age_missing"] == [("r#1",)] and "attendee_age" not in facts
    (review,) = capacity_status(data)[0].needs_review
    assert review.reasons == ("missing_birth_year",)


def test_the_same_age_range_for_both_genders_does_not_overlap() -> None:
    combos = {**BASE["defaults"]["combos"], "m25_29": {"gender": "male", "age": [25, 29]}}
    assert set(policy(combos=combos).defaults.combos) == {"f25_29", "m25_29"}


def test_combo_is_a_reserved_dimension_name() -> None:
    with pytest.raises(ValidationError, match="built in"):
        EventPolicy.model_validate(
            {**BASE, "dimensions": {"choices": {"combo": {"values": ["a"]}}}}
        )


def test_a_session_adds_or_replaces_combinations_by_id() -> None:
    added = with_session(
        combos={"m28_33": {"gender": "male", "age": [28, 33]}},
        targets={"combo": {"m28_33": {"lo": 1}}},
    )
    rows = scenario_facts(added).rows["combo_def"]
    assert ("s", "f25_29", "female", 25, 29) in rows and ("s", "m28_33", "male", 28, 33) in rows
    with pytest.raises(ValidationError, match="overlap"):
        with_session(combos={"f28_31": {"gender": "female", "age": [28, 31]}})
    with pytest.raises(ValidationError, match="undeclared"):
        with_session(targets={"combo": {"m28_33": {"lo": 1}}})


@pytest.mark.parametrize(
    ("defaults", "message"),
    [
        ({"targets": {"combo": {"f25_29": {"lo": 11}}}}, "exceeds capacity 10"),
        (
            {"targets": {"gender": {"female": {"hi": 3}}, "combo": {"f25_29": {"lo": 4}}}},
            "add up to 4, above the female maximum 3",
        ),
        (
            {
                "combos": {
                    **BASE["defaults"]["combos"],
                    "f30_34": {"gender": "female", "age": [30, 34]},
                },
                "targets": {"combo": {"f25_29": {"lo": 6}, "f30_34": {"lo": 5}}},
            },
            "add up to 11, above the female maximum 10",  # capacity when female has no target
        ),
    ],
)
def test_combination_minimums_must_fit_under_the_gender(defaults: Any, message: str) -> None:
    scenario_ = Scenario.model_validate(
        {
            "policy": {**BASE, "defaults": {**BASE["defaults"], **defaults}},
            "now": NOW,
            "sessions": [{"id": "s", "date": "2026-11-14"}],
        }
    )
    with pytest.raises(ValueError, match=message):
        resolve_targets(scenario_.policy, scenario_.sessions[0])


def test_rules_count_gender_and_age_with_inclusive_bounds() -> None:
    data = scenario("combo")
    s1, s2, _ = capacity_status(data)
    counts = {(v.dim, v.value): (v.filled, v.pending, v.gap) for v in s1.values}
    # 25 (r2) and 28 (r1) are in 25~29, 26 (r4) is waiting for payment, 30 (r3) is not.
    assert counts[("combo", "f25_29")] == (2, 1, 1)
    assert counts[("combo", "f30_34")] == (1, 0, 0)
    assert counts[("gender", "female")] == (4, 1, 0)  # r6 still counts as a woman
    s2_counts = {(v.dim, v.value): (v.filled, v.gap) for v in s2.values}
    assert s2_counts[("combo", "m28_33")] == (2, 1)  # 32 (r8) and 33 (r11) in, 27 (r9) out
    assert ("combo", "f25_29") not in s2_counts  # s2's targets replace the default combo goals
    (young_women,) = [v for v in s1.values if v.value == "f25_29"]
    assert young_women.evidence == (
        "target/s1/combo/f25_29",
        "combo_def/s1/f25_29",
        "session_capacity/s1",
        "registration/r1",
        "registration/r2",
    )


def test_a_missing_birth_year_is_flagged_and_left_out_of_ages() -> None:
    data = scenario("combo")
    facts = scenario_facts(data).rows
    assert facts["age_missing"] == [("r6#1",)]
    assert all(row[0] != "r6#1" for row in facts["attendee_age"])
    (review,) = capacity_status(data)[0].needs_review
    assert review.reasons == ("missing_birth_year",) and "r6" in review.message
    assert review.evidence == ("registration/r6", "age_missing/r6#1")


def test_events_without_ages_get_no_age_facts() -> None:
    facts = scenario_facts(scenario("hybrid")).rows
    assert "attendee_age" not in facts and "age_missing" not in facts and "combo_def" not in facts


def test_combo_scenario_holds_s1_and_keeps_capped_s2_quiet() -> None:
    decisions = promotion_decisions(scenario("combo"))
    # s1: female full (4 confirmed + 1 waiting of 5) while 25~29 is 1 short -> target conflict.
    (held,) = [d for d in decisions if d.parts and d.session == "s1"]
    assert (held.session, held.kind, held.reasons, held.need) == ("s1", "hold", ("gender_room",), 1)
    # s2: male is capped by the ratio, so its 28~33 shortfall is not promoted.
    assert all(not d.parts for d in decisions if d.session == "s2")
    # s3: women 26 and 31 of 5 wanted, 25~29 at least 4 -> one line, 3 people, 3 of them 25~29.
    (female,) = [d for d in decisions if d.session == "s3" and d.value == "female"]
    assert female.message == (
        "회차 임박: female 3명 부족, 홍보가 필요합니다. "
        "광고 대상: female 25~29세(연 나이) 3명 이상."
    )


def test_report_nests_combinations_under_their_gender() -> None:
    lines = report(SCENARIOS / "combo.yaml")
    female = lines.index("  gender=female: 확정 4 · 대기 1 · 목표 5~5 · 목표 충족")
    assert lines[female + 1 : female + 3] == [
        "    └ female 25~29세(연 나이): 확정 2 · 대기 1 · 목표 4~10 · 부족 1",
        "    └ female 30~34세(연 나이): 확정 1 · 대기 0 · 목표 1~10",
    ]
    assert "    └ male 28~33세(연 나이): 확정 2 · 대기 0 · 목표 3~10 · 부족 1" in lines
    payload = report_json(run_report(SCENARIOS / "combo.yaml"))
    assert payload["schema"] == "event-ops/report@1"  # an added field keeps the version
    assert payload["sessions"][1]["combos"]["m28_33"] == {
        "gender": "male",
        "age": [28, 33],
        "label": "male 28~33세(연 나이)",
    }
