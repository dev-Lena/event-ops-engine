"""Similar age (#91 A): each gender's ages per pool, for events that declare `similar_age`."""

import json
from pathlib import Path

import pytest

from event_ops_engine.capacity import AgeGroup, capacity_status, session_status
from event_ops_engine.cli import report, report_json, run_report
from event_ops_engine.clock import to_epoch
from event_ops_engine.engine import Engine
from event_ops_engine.facts import registration_facts, scenario_facts
from event_ops_engine.loader import load_policy, load_scenario
from tests.conftest import REPO, SCENARIOS, loaded, scenario

POLICY = REPO / "policy" / "events" / "synthetic-similar-age.yaml"


def groups(engine: Engine, session: str = "s1") -> dict[tuple[str, str], tuple[int, ...]]:
    return {(g.gender, g.pool): g.ages for g in session_status(engine, session).ages}


def test_report_shows_each_genders_ages_per_pool() -> None:
    lines = report(SCENARIOS / "similar-age.yaml")
    female = lines.index("  gender=female: 확정 2 · 대기 1 · 목표 4~4 · 부족 1")
    assert lines[female + 1 : female + 3] == [
        "    나이(연 나이) 확정·대기: 26 · 28 · 28 — 26~28세, 폭 2살",
        "    나이(연 나이) 신청 접수: 24 · 41 — 24~41세, 폭 17살",
    ]
    male = lines.index("  gender=male: 확정 2 · 대기 0 · 목표 4~4 · 부족 2")
    assert lines[male + 1 : male + 3] == [
        "    나이(연 나이) 확정·대기: 31 · 33 — 31~33세, 폭 2살",
        "    나이(연 나이) 신청 접수: 없음 · 출생연도 없음·오류 1명 제외",
    ]
    # s2: ages come before the gender's combinations; male has no target line of its own.
    s2 = lines.index("  gender=female: 확정 2 · 대기 0 · 목표 4~4 · 부족 2")
    assert lines[s2 + 1 : s2 + 4] == [
        "    나이(연 나이) 확정·대기: 30 · 37 — 30~37세, 폭 7살",
        "    └ female 27~32세(연 나이): 확정 1 · 대기 0 · 목표 2~8 · 부족 1",
        "  male 나이(연 나이) 확정·대기: 32 — 32세, 폭 0살",
    ]


def test_people_of_the_same_age_both_count_and_cancelled_ones_do_not(engine: Engine) -> None:
    loaded(engine, "similar-age")
    female, female_applied, male, male_applied = session_status(engine, "s1").ages
    assert female == AgeGroup("female", "occupying", (26, 28, 28), 26, 28, 2, 0)
    assert female_applied == AgeGroup("female", "applied", (24, 41), 24, 41, 17, 0)
    assert male == AgeGroup("male", "occupying", (31, 33), 31, 33, 2, 0)  # r8 (36) cancelled
    assert male_applied == AgeGroup("male", "applied", (), None, None, None, 1)


def test_cancellation_by_status_event_updates_ages(engine: Engine) -> None:
    data = loaded(engine, "similar-age")
    engine.insert("status_event", ("r3", to_epoch(data.now) - 60, "cancelled"))  # female 28
    assert groups(engine)[("female", "occupying")] == (26, 28)


def test_cancellation_by_retracting_facts_updates_ages(engine: Engine) -> None:
    data = loaded(engine, "similar-age")
    engine.retract(registration_facts(data, data.registrations[1]))  # r2, female 26
    female = session_status(engine, "s1").ages[0]
    assert (female.gender, female.pool) == ("female", "occupying")
    assert (female.ages, female.low, female.spread) == ((28, 28), 28, 0)


def test_selecting_an_applicant_moves_the_age_to_the_seat_holders(engine: Engine) -> None:
    data = loaded(engine, "similar-age")
    engine.insert("status_event", ("r4", to_epoch(data.now) - 60, "pending_payment"))  # 41
    ages = {(g.gender, g.pool): g for g in session_status(engine, "s1").ages}
    assert ages[("female", "occupying")].ages == (26, 28, 28, 41)
    assert ages[("female", "occupying")].spread == 15
    assert ages[("female", "applied")].ages == (24,)


def test_a_missing_birth_year_is_counted_in_its_pool_and_raised_once_seated(
    engine: Engine,
) -> None:
    data = loaded(engine, "similar-age")
    assert not session_status(engine, "s1").needs_review  # r7 is only applied so far
    engine.insert("status_event", ("r7", to_epoch(data.now) - 60, "confirmed"))
    status = session_status(engine, "s1")
    male = {g.pool: g for g in status.ages if g.gender == "male"}
    assert set(male) == {"occupying"}
    assert (male["occupying"].ages, male["occupying"].unknown) == ((31, 33), 1)
    assert [r.reasons for r in status.needs_review] == [("missing_birth_year",)]


def test_events_without_similar_age_get_no_age_lines() -> None:
    data = scenario("single")  # age bands only
    assert all(status.ages == () for status in capacity_status(data))
    facts = scenario_facts(data).rows
    assert "similar_age" not in facts and "attendee_age" not in facts
    payload = report_json(run_report(SCENARIOS / "single.yaml"))
    assert all(session["ages"] == [] for session in payload["sessions"])


def test_json_lists_ages_without_naming_anyone() -> None:
    payload = json.loads(json.dumps(report_json(run_report(SCENARIOS / "similar-age.yaml"))))
    assert payload["schema"] == "event-ops/report@1"  # an added field keeps the version
    ages = payload["sessions"][0]["ages"]
    assert ages[0] == {
        "gender": "female",
        "pool": "occupying",
        "ages": [26, 28, 28],
        "low": 26,
        "high": 28,
        "spread": 2,
        "unknown": 0,
    }
    assert all(set(group) == set(ages[0]) for group in ages)  # no registration or attendee ids


def test_a_blank_similar_age_key_is_refused(tmp_path: Path) -> None:
    blank = tmp_path / "policy.yaml"
    blank.write_text(
        POLICY.read_text(encoding="utf-8").replace("similar_age: {}", "similar_age:"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="similar_age is blank"):
        load_policy(blank)
    run = tmp_path / "scenario.yaml"
    run.write_text(
        (SCENARIOS / "similar-age.yaml")
        .read_text(encoding="utf-8")
        .replace("../../../policy/events/synthetic-similar-age.yaml", "policy.yaml"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="similar_age is blank"):
        load_scenario(run)
    assert load_policy(POLICY).similar_age is not None
