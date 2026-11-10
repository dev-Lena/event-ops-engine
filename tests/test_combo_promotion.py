"""Combination recommendations (#32): nested under the gender, held when they can't fit."""

from typing import Any

from event_ops_engine.decision import Decision, DecisionKind
from event_ops_engine.model import Scenario
from event_ops_engine.promotion import promotion_decisions

NOW = "2026-11-07T10:00:00+09:00"
COMBOS = {
    "f25_29": {"gender": "female", "age": [25, 29]},
    "f30_34": {"gender": "female", "age": [30, 34]},
}


def woman(reg: str, birth_year: int) -> dict[str, Any]:
    return person(reg, "female", birth_year)


def person(reg: str, gender: str, birth_year: int) -> dict[str, Any]:
    return {
        "id": reg,
        "session": "s",
        "members": [{"gender": gender, "birth_year": birth_year}],
        "status_events": [{"at": "2026-10-20T10:00:00+09:00", "status": "confirmed"}],
    }


def decide(
    targets: dict[str, Any],
    people: list[dict[str, Any]],
    capacity: int = 16,
    ratios: list[dict[str, Any]] | None = None,
    session: dict[str, Any] | None = None,
) -> list[Decision]:
    """Decisions for one session 5 days out (inside lead_days 7, no recent sign-ups)."""
    policy = {
        "event": "e",
        "defaults": {
            "capacity": capacity,
            "combos": COMBOS,
            "targets": targets,
            "ratios": ratios or [],
        },
        "promotion": {"lead_days": 7, "trend_min_per_week": 3},
    }
    data = Scenario.model_validate(
        {
            "policy": policy,
            "now": NOW,
            "sessions": [{"id": "s", "date": "2026-11-12", **(session or {})}],
            "registrations": people,
        }
    )
    return promotion_decisions(data)


def only(decisions: list[Decision], kind: DecisionKind, value: str) -> Decision:
    (found,) = [d for d in decisions if d.kind == kind and d.value == value]
    return found


def test_the_gender_line_carries_its_combinations_as_ad_targets() -> None:
    # Women: 26 and 31. Female 5 wanted -> 3 short; each combination 2 wanted -> 1 short.
    targets = {"gender": {"female": {"lo": 5}}, "combo": {"f25_29": {"lo": 2}, "f30_34": {"lo": 2}}}
    decisions = decide(targets, [woman("r1", 2000), woman("r2", 1995)])
    female = only(decisions, DecisionKind.RECOMMEND, "female")
    assert female.dim == "gender" and female.need == 3  # the gender's own shortfall is larger
    assert [(p.value, p.need) for p in female.parts] == [("f25_29", 1), ("f30_34", 1)]
    assert female.message == (
        "회차 임박: female 3명 부족, 홍보가 필요합니다. 광고 대상: female 25~29세(연 나이) "
        "1명 이상, female 30~34세(연 나이) 1명 이상."
    )
    assert {"target/s/combo/f25_29", "combo_def/s/f30_34", "registration/r1"} <= set(
        female.evidence
    )
    assert all(d.dim != "combo" for d in decisions)  # never a second, overlapping line


def test_need_is_the_sum_of_combination_shortfalls_when_it_is_larger() -> None:
    # One woman aged 40 sits outside both ranges: female is 2 short, the ranges 2 + 2, and
    # the room left (5 - 1) is exactly 4, so it still fits: no conflict at equality.
    targets = {
        "gender": {"female": {"lo": 3, "hi": 5}},
        "combo": {"f25_29": {"lo": 2}, "f30_34": {"lo": 2}},
    }
    female = only(decide(targets, [woman("r1", 1986)]), DecisionKind.RECOMMEND, "female")
    assert female.need == 4 and [p.need for p in female.parts] == [2, 2]


def test_combinations_alone_are_named_directly() -> None:
    # No gender target: the shortfall is the combination's own, and the room is the session's.
    decisions = decide({"combo": {"f25_29": {"lo": 2}}}, [woman("r1", 2000)])
    (rec,) = [d for d in decisions if d.kind == DecisionKind.RECOMMEND]
    assert (rec.dim, rec.value, rec.need) == ("gender", "female", 1)
    assert rec.message == "회차 임박: female 25~29세(연 나이) 1명 부족, 홍보가 필요합니다."


def test_a_capped_gender_keeps_its_combinations_quiet() -> None:
    # Women 3 (aged 40) vs men 1 with max_diff 1: female is capped, though not full.
    targets = {
        "gender": {"female": {"lo": 3, "hi": 10}},
        "combo": {"f25_29": {"lo": 2}, "f30_34": {"lo": 2}},
    }
    people = [woman(f"r{i}", 1986) for i in range(3)] + [person("m1", "male", 1990)]
    ratio = [{"dim": "gender", "values": ["female", "male"], "max_diff": 1}]
    decisions = decide(targets, people, ratios=ratio)
    assert any(d.kind == DecisionKind.CAP and d.value == "female" for d in decisions)
    assert all(not d.parts for d in decisions)


def test_shortfalls_beyond_the_genders_room_are_held_as_a_target_conflict() -> None:
    # Female at most 4; a woman aged 40 takes a seat, leaving room 3 for 2 + 2 in range.
    targets = {
        "gender": {"female": {"lo": 3, "hi": 4}},
        "combo": {"f25_29": {"lo": 2}, "f30_34": {"lo": 2}},
    }
    decisions = decide(targets, [woman("r1", 1986)])
    own = only(decisions, DecisionKind.RECOMMEND, "female")
    assert own.need == 2 and not own.parts  # the gender's own gap can still be promoted
    held = only(decisions, DecisionKind.HOLD, "female")
    assert held.reasons == ("gender_room",) and held.need == 4
    assert held.message == (
        "목표 충돌: female 조합 부족 합 4명(female 25~29세(연 나이) 2명, female 30~34세(연 나이) "
        "2명)이 female 남은 자리 3명보다 많습니다. 조합 목표나 female 목표를 운영자가 확인해 주세요."
    )


def test_a_full_gender_holds_its_combinations() -> None:
    targets = {
        "gender": {"female": {"lo": 2, "hi": 2}},
        "combo": {"f25_29": {"lo": 1}, "f30_34": {"lo": 1}},
    }
    decisions = decide(targets, [woman("r1", 1986), woman("r2", 1986)])
    assert [(d.kind, d.value, d.need) for d in decisions] == [(DecisionKind.HOLD, "female", 2)]
    assert "남은 자리 0명" in decisions[0].message


def test_a_full_session_holds_combinations_under_the_gender() -> None:
    targets = {"combo": {"f25_29": {"lo": 1}}}
    people = [woman("r1", 1986), woman("r2", 1986), person("m1", "male", 1990)]
    (held,) = decide(targets, people, capacity=3)
    assert (held.kind, held.reasons, held.value) == (DecisionKind.HOLD, ("session_full",), "female")
    assert held.message.startswith("정원 마감: female 25~29세(연 나이) 1명 부족이 남았지만")


def test_past_the_promotion_cutoff_combinations_stay_quiet() -> None:
    # Session today at 11:00, cutoff 2 hours before: now (10:00) is past it.
    targets = {"combo": {"f25_29": {"lo": 2}}}
    session = {"date": "2026-11-07", "start_time": "11:00"}
    assert decide(targets, [woman("r1", 2000)], session=session) == []


def test_without_a_gender_target_the_sessions_room_decides_the_conflict() -> None:
    # Capacity 3, two men seated: one seat left for two women aged 25~29.
    people = [person("m1", "male", 1990), person("m2", "male", 1990)]
    (held,) = decide({"combo": {"f25_29": {"lo": 2}}}, people, capacity=3)
    assert (held.kind, held.reasons, held.need) == (DecisionKind.HOLD, ("gender_room",), 2)
    assert "남은 자리 1명" in held.message


def test_a_slow_trend_alone_recommends_a_combination_with_only_its_evidence() -> None:
    # 20 days out (outside lead_days 7): no lead_time. Female has its 2 (aged 40); 25~29 is
    # 1 short with no confirmation this week, so only slow_trend fires, for the combination.
    targets = {"gender": {"female": {"lo": 2}}, "combo": {"f25_29": {"lo": 1}}}
    session = {"date": "2026-11-27"}
    (rec,) = decide(targets, [woman("r1", 1986), woman("r2", 1986)], session=session)
    assert rec.reasons == ("slow_trend",) and rec.need == 1
    assert rec.message == "신청 추세 느림: female 25~29세(연 나이) 1명 부족, 홍보를 권합니다."
    assert "registration/r1" not in rec.evidence and "target/s/gender/female" not in rec.evidence
    assert {"target/s/combo/f25_29", "combo_def/s/f25_29"} <= set(rec.evidence)


def test_a_full_session_never_counts_a_ratio_difference_as_people() -> None:
    # Capacity 4: three men, one woman aged 40 -> full. Female trails by 2 (a ratio
    # difference, held as session_full), and 25~29 is 1 short: the hold needs 1 person, not 2.
    people = [person(f"m{i}", "male", 1990) for i in range(3)] + [woman("r1", 1986)]
    ratio = [{"dim": "gender", "values": ["female", "male"], "max_diff": 1}]
    decisions = decide({"combo": {"f25_29": {"lo": 1}}}, people, capacity=4, ratios=ratio)
    held = only(decisions, DecisionKind.HOLD, "female")
    assert held.reasons == ("session_full",) and held.need == 1
