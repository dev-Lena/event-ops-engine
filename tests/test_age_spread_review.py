"""Similar age (#91 B): a review when a gender's seat holders spread wider than the limit."""

from typing import Any

import pytest
from pydantic import ValidationError

from event_ops_engine.capacity import session_status
from event_ops_engine.cli import report, report_json, run_report
from event_ops_engine.clock import to_epoch
from event_ops_engine.decision import Decision
from event_ops_engine.engine import Engine
from event_ops_engine.facts import scenario_facts
from event_ops_engine.model import Scenario
from event_ops_engine.policy import resolve_max_spread
from tests.conftest import SCENARIOS, loaded, scenario

POLICY: dict[str, Any] = {
    "event": "e",
    "similar_age": {"max_spread": 12},
    "defaults": {"capacity": 8},
    "promotion": {"lead_days": 7, "trend_min_per_week": 3},
}


def spread_reviews(engine: Engine, session: str) -> list[Decision]:
    return [d for d in session_status(engine, session).needs_review if d.reasons == ("age_spread",)]


def test_seat_holders_spread_past_the_limit_raise_one_review_for_that_gender(
    engine: Engine,
) -> None:
    loaded(engine, "similar-age")
    (review,) = spread_reviews(engine, "s3")  # women 27 (confirmed) and 41 (waiting): 14 > 12
    assert (review.kind, review.dim, review.value) == ("ask", "gender", "female")
    assert review.message == (
        "나이 폭 확인: female 확정·대기 폭 14살(27~41세, 연 나이)이 기준 12살을 넘습니다. "
        "선별 · 광고 나이를 확인해 주세요."
    )
    # The event's setting is the evidence; no registration is named.
    assert review.evidence == ("similar_age/s3", "age_spread_limit/s3")
    assert "  확인 요청: " + review.message in report(SCENARIOS / "similar-age.yaml")
    s3 = report_json(run_report(SCENARIOS / "similar-age.yaml"))["sessions"][2]
    assert s3["session"] == "s3"
    assert [r for r in s3["needs_review"] if r["reasons"] == ["age_spread"]] == [
        review.model_dump(mode="json")
    ]
    assert s3["needs_review"][0]["dim"] == "gender" and s3["needs_review"][0]["value"] == "female"


def test_sign_ups_not_yet_picked_never_raise_it(engine: Engine) -> None:
    loaded(engine, "similar-age")
    applied = {(g.gender, g.pool): g.spread for g in session_status(engine, "s1").ages}
    assert applied[("female", "applied")] == 17  # wider than 12, but nobody picked them yet
    assert spread_reviews(engine, "s1") == []


def test_a_session_limit_overrides_the_events() -> None:
    data = scenario("similar-age")
    limits = {s.id: resolve_max_spread(data.policy, s) for s in data.sessions}
    assert limits == {"s1": 12, "s2": 12, "s3": 12, "s4": 15}
    assert ("s4", 15) in scenario_facts(data).rows["age_spread_limit"]
    s4 = report_json(run_report(SCENARIOS / "similar-age.yaml"))["sessions"][3]
    assert s4["session"] == "s4" and s4["needs_review"] == []  # same 14 years, limit 15


@pytest.mark.parametrize("limit, raised", [(13, True), (14, False), (15, False)])
def test_a_spread_equal_to_the_limit_is_within_it(engine: Engine, limit: int, raised: bool) -> None:
    loaded(engine, "similar-age")
    engine.remove("age_spread_limit", ("s3", 12))
    engine.insert("age_spread_limit", ("s3", limit))
    assert bool(spread_reviews(engine, "s3")) is raised


def test_cancelling_a_seat_holder_clears_the_review(engine: Engine) -> None:
    data = loaded(engine, "similar-age")
    engine.insert("status_event", ("r13", to_epoch(data.now) - 60, "cancelled"))  # the 41
    assert spread_reviews(engine, "s3") == []


def test_past_sessions_are_left_alone(engine: Engine) -> None:
    loaded(engine, "similar-age")
    ((_, days),) = engine.rows("days_left", "s3")
    engine.remove("days_left", ("s3", days))
    engine.insert("days_left", ("s3", -1))
    assert spread_reviews(engine, "s3") == []
    assert session_status(engine, "s3").ages  # the ages are still shown


def test_without_a_limit_there_is_no_review_fact() -> None:
    data = Scenario.model_validate(
        {
            "policy": {**POLICY, "similar_age": {}},
            "now": "2026-11-10T10:00:00+09:00",
            "sessions": [{"id": "s", "date": "2026-11-20"}],
        }
    )
    assert resolve_max_spread(data.policy, data.sessions[0]) is None
    assert "age_spread_limit" not in scenario_facts(data).rows


def test_a_session_cannot_turn_similar_age_on_alone() -> None:
    policy = {key: value for key, value in POLICY.items() if key != "similar_age"}
    session = {"id": "s", "date": "2026-11-20", "similar_age": {"max_spread": 10}}
    with pytest.raises(ValidationError, match="doesn't declare it"):
        Scenario.model_validate(
            {"policy": policy, "now": "2026-11-10T10:00:00+09:00", "sessions": [session]}
        )


def test_a_negative_limit_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Scenario.model_validate(
            {
                "policy": {**POLICY, "similar_age": {"max_spread": -1}},
                "now": "2026-11-10T10:00:00+09:00",
                "sessions": [{"id": "s", "date": "2026-11-20"}],
            }
        )
