"""Similar age (#91 C): age ranges as wide as the limit that hold the most seat holders."""

import json
from typing import Any

from event_ops_engine.capacity import RangeSuggestion, session_status
from event_ops_engine.cli import report, report_json, run_report
from event_ops_engine.clock import to_epoch
from event_ops_engine.engine import Engine
from event_ops_engine.facts import scenario_facts
from event_ops_engine.model import Scenario
from tests.conftest import SCENARIOS, loaded

TAIL = "고른 범위를 조합으로 적으면 광고 대상이 됩니다."


def suggestion(engine: Engine, session: str, gender: str) -> RangeSuggestion | None:
    found = {s.gender: s for s in session_status(engine, session).range_suggestions}
    return found.get(gender)


def test_report_suggests_a_centred_range_and_lists_ties() -> None:
    lines = report(SCENARIOS / "similar-age.yaml")
    # s1 women 26 · 28 · 28 (applicants 24 · 41 don't count): centred 12-year range.
    assert (
        "    나이 범위 제안(지금 확정·대기 기준, 폭 12살, 연 나이): 21~33세 — 3명 중 3명 포함. "
        + TAIL
    ) in lines
    # s3 women 27 and 41 can't share 12 years: both ranges, the person in charge picks.
    assert (
        "    나이 범위 제안(지금 확정·대기 기준, 폭 12살, 연 나이): 21~33세 또는 35~47세 — "
        "2명 중 1명씩 포함. " + TAIL
    ) in lines
    # s4 has the same women but a 15-year session limit: one range holds both.
    assert (
        "    나이 범위 제안(지금 확정·대기 기준, 폭 15살, 연 나이): 27~42세 — 2명 중 2명 포함. "
        + TAIL
    ) in lines


def test_people_of_the_same_age_count_once_each(engine: Engine) -> None:
    loaded(engine, "similar-age")
    assert suggestion(engine, "s1", "female") == RangeSuggestion(
        "female", ((21, 33),), covered=3, seated=3, width=12
    )


def test_an_odd_spare_year_goes_to_the_older_side(engine: Engine) -> None:
    loaded(engine, "similar-age")
    engine.remove("age_spread_limit", ("s1", 12))
    engine.insert("age_spread_limit", ("s1", 11))  # 26~28 leaves 9 spare years: 4 below, 5 above
    found = suggestion(engine, "s1", "female")
    assert found is not None and found.ranges == ((22, 33),)


def test_people_exactly_the_limit_apart_share_one_range(engine: Engine) -> None:
    loaded(engine, "similar-age")
    engine.remove("age_spread_limit", ("s3", 12))
    engine.insert("age_spread_limit", ("s3", 14))  # s3 women 27 and 41: "within 14 years"
    found = suggestion(engine, "s3", "female")
    assert found is not None and (found.ranges, found.covered) == (((27, 41),), 2)


def test_a_gender_with_a_combination_gets_no_suggestion(engine: Engine) -> None:
    loaded(engine, "similar-age")
    assert suggestion(engine, "s2", "female") is None  # f27_32 is written already
    assert suggestion(engine, "s2", "male") is not None
    lines = report(SCENARIOS / "similar-age.yaml")
    assert any(line.startswith("  male 나이 범위 제안(") for line in lines)  # no male target line


def test_seat_changes_move_the_suggestion(engine: Engine) -> None:
    data = loaded(engine, "similar-age")
    engine.insert("status_event", ("r13", to_epoch(data.now) - 60, "cancelled"))  # s3's 41
    found = suggestion(engine, "s3", "female")
    assert found is not None and (found.ranges, found.covered, found.seated) == (
        ((21, 33),),
        1,
        1,
    )


def test_past_sessions_get_no_suggestion(engine: Engine) -> None:
    loaded(engine, "similar-age")
    ((_, days),) = engine.rows("days_left", "s1")
    engine.remove("days_left", ("s1", days))
    engine.insert("days_left", ("s1", -1))
    assert session_status(engine, "s1").range_suggestions == ()


def test_without_a_limit_there_is_nothing_to_suggest(engine: Engine) -> None:
    policy: dict[str, Any] = {
        "event": "e",
        "similar_age": {},
        "defaults": {"capacity": 8},
        "promotion": {"lead_days": 7, "trend_min_per_week": 3},
    }
    data = Scenario.model_validate(
        {
            "policy": policy,
            "now": "2026-11-10T10:00:00+09:00",
            "sessions": [{"id": "s", "date": "2026-11-20"}],
            "registrations": [
                {
                    "id": "r1",
                    "session": "s",
                    "members": [{"gender": "female", "birth_year": 1998}],
                    "status_events": [{"at": "2026-11-01T10:00:00+09:00", "status": "confirmed"}],
                }
            ],
        }
    )
    engine.load(scenario_facts(data))
    status = session_status(engine, "s")
    assert status.ages and status.range_suggestions == ()


def test_json_carries_ranges_and_counts_only() -> None:
    payload = json.loads(json.dumps(report_json(run_report(SCENARIOS / "similar-age.yaml"))))
    s3 = payload["sessions"][2]
    assert s3["range_suggestions"] == [
        {
            "gender": "female",
            "ranges": [[21, 33], [35, 47]],
            "covered": 1,
            "seated": 2,
            "width": 12,
        },
        {"gender": "male", "ranges": [[24, 36]], "covered": 1, "seated": 1, "width": 12},
    ]
    single = json.loads(json.dumps(report_json(run_report(SCENARIOS / "single.yaml"))))
    assert all(session["range_suggestions"] == [] for session in single["sessions"])
