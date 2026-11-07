"""Module ③ promotion judgement: reasons, holds, inactive sessions, evidence."""

from event_ops_engine.decision import Decision
from event_ops_engine.engine import Engine
from event_ops_engine.promotion import promotion_decisions, session_promotion
from tests.conftest import loaded, scenario


def by_value(decisions: list[Decision]) -> dict[tuple[str, str], Decision]:
    """Recommend / hold decisions keyed by value; cap decisions are read with `caps`."""
    return {(d.dim or "", d.value or ""): d for d in decisions if d.kind != "cap"}


def caps(decisions: list[Decision]) -> dict[tuple[str, str], Decision]:
    return {(d.dim or "", d.value or ""): d for d in decisions if d.kind == "cap"}


def test_slow_trend_and_imbalance_recommend_promotion(engine: Engine) -> None:
    loaded(engine, "single")  # 14 days left: outside lead_days
    decisions = by_value(session_promotion(engine, "s1"))
    # 20s: 1 confirmed + 1 pending reaches lo 2, so there is no gap and nothing to promote
    # female (3 vs male 1) is capped and therefore not promoted
    assert {k for k, d in decisions.items() if d.kind == "recommend"} == {
        ("gender", "male"),
        ("age_band", "30s"),
    }
    assert decisions[("gender", "male")].reasons == ("imbalance", "slow_trend")
    assert decisions[("gender", "male")].need == 5


def test_lead_time_fires_inside_lead_days(engine: Engine) -> None:
    loaded(engine, "pair-mixed")  # 3 days left
    decisions = by_value(session_promotion(engine, "s2"))
    assert ("gender", "female") not in decisions  # capped (3 vs 1): never promoted
    assert decisions[("gender", "male")].reasons == ("imbalance", "lead_time", "slow_trend")
    assert ("age_band", "20s") not in decisions  # target met
    assert decisions[("age_band", "30s")].need == 2


def test_enough_recent_confirmations_mean_no_slow_trend(engine: Engine) -> None:
    loaded(engine, "group")
    decisions = by_value(session_promotion(engine, "s3"))
    assert ("gender", "female") not in decisions  # 3 confirmed this week == trend_min_per_week
    assert decisions[("gender", "male")].reasons == ("slow_trend",)
    assert decisions[("age_band", "20s")].need == 2


def test_balanced_session_with_healthy_trend_gets_no_decision(engine: Engine) -> None:
    loaded(engine, "ratio")
    assert session_promotion(engine, "s4a") == []


def test_full_session_turns_gaps_into_holds(engine: Engine) -> None:
    loaded(engine, "ratio")
    decisions = session_promotion(engine, "s4b")
    assert {d.kind for d in decisions} == {"hold"}
    male = by_value(decisions)[("gender", "male")]
    assert male.reasons == ("session_full",)
    assert male.need == 3
    assert "정원 마감" in male.message


def test_lead_days_boundary_is_inclusive_and_past_sessions_are_silent(engine: Engine) -> None:
    loaded(engine, "boundary")
    today = by_value(session_promotion(engine, "s5a"))  # exactly 7 days left
    assert today[("gender", "female")].reasons == ("lead_time",)
    assert today[("age_band", "30s")].reasons == ("lead_time", "slow_trend")  # 2 recent < 3
    assert session_promotion(engine, "s5b") == []  # happened yesterday


def test_evidence_lists_inputs_behind_the_recommendation(engine: Engine) -> None:
    loaded(engine, "pair-mixed")
    male = by_value(session_promotion(engine, "s2"))[("gender", "male")]
    assert male.evidence == (
        "session_capacity/s2",
        "days_left/s2",
        "target/s2/gender/male",
        "ratio_target/s2/gender",
        "policy/s2/lead_days",
        "policy/s2/trend_min_per_week",
        "now",
        "registration/r1",
    )


def test_promotion_decisions_without_engine_cover_all_sessions() -> None:
    decisions = promotion_decisions(scenario("ratio"))
    assert {d.session for d in decisions} == {"s4b"}


def test_mixed_reasons_take_need_and_message_from_the_gap_reason(engine: Engine) -> None:
    loaded(engine, "single")
    male = by_value(session_promotion(engine, "s1"))[("gender", "male")]
    assert male.reasons == ("imbalance", "slow_trend")
    assert male.need == 5  # target shortfall, not the ratio difference
    assert male.message.startswith("신청 추세 느림: male 5명 부족")


def test_past_full_session_gets_no_hold(engine: Engine) -> None:
    loaded(engine, "boundary")
    assert engine.rows("session_full", "s5c")  # capacity 1, one confirmed
    assert engine.rows("gap", "s5c", "gender", "male") == [("s5c", "gender", "male", 1)]
    assert session_promotion(engine, "s5c") == []


def test_session_full_by_pending_payments_also_blocks_promotion(engine: Engine) -> None:
    # single: capacity 12, 4 confirmed, 1 pending. Fill the rest with pending registrations.
    from datetime import datetime, timezone

    from event_ops_engine.facts import registration_facts
    from event_ops_engine.model import Member, Registration, StatusEvent

    data = loaded(engine, "single")
    at = datetime(2026, 11, 5, tzinfo=timezone.utc)
    for i in range(7):
        extra = Registration(
            id=f"p{i}",
            session="s1",
            members=(Member(gender="female", birth_year=1995),),
            status_events=(StatusEvent(at=at, status="pending_payment"),),
        )
        engine.load(registration_facts(data, extra))
    assert engine.rows("session_full", "s1")
    decisions = by_value(session_promotion(engine, "s1"))
    assert decisions and all(d.kind == "hold" for d in decisions.values())


# --- temporary cap for the leading ratio side (#51) ---------------------------------------


def test_leading_gender_gets_a_cap_at_partner_plus_max_diff(engine: Engine) -> None:
    loaded(engine, "pair-mixed")  # female 3, male 1, max_diff 1
    cap = caps(session_promotion(engine, "s2"))[("gender", "female")]
    assert (cap.kind, cap.need, cap.reasons) == ("cap", 2, ("imbalance",))
    assert "상한 2명" in cap.message and "male 1명" in cap.message
    assert "ratio_target/s2/gender" in cap.evidence and "registration/r1" in cap.evidence
    assert ("gender", "male") not in caps(session_promotion(engine, "s2"))


def test_issue_example_ten_women_three_men_caps_women_at_four() -> None:
    from datetime import datetime, timezone

    from event_ops_engine.facts import scenario_facts
    from event_ops_engine.model import Member, Registration

    base = scenario("ratio")
    at = datetime(2026, 11, 1, tzinfo=timezone.utc)
    regs = tuple(
        Registration(
            id=f"w{i}" if i < 10 else f"m{i}",
            session="s4a",
            members=(Member(gender="female" if i < 10 else "male", birth_year=1995),),
            status_events=({"at": at, "status": "confirmed"},),
        )
        for i in range(13)
    )
    session = base.sessions[0].model_copy(update={"capacity": 30})
    data = base.model_copy(update={"sessions": (session,), "registrations": regs})
    with Engine() as own:
        own.load(scenario_facts(data))
        cap = caps(session_promotion(own, "s4a"))[("gender", "female")]
    assert cap.need == 4


def test_balanced_or_full_sessions_get_no_cap(engine: Engine) -> None:
    loaded(engine, "ratio")
    assert caps(session_promotion(engine, "s4a")) == {}  # 5 vs 5
    assert caps(session_promotion(engine, "s4b")) == {}  # 6 vs 3 but the session is full


def test_difference_equal_to_max_diff_is_not_capped(engine: Engine) -> None:
    data = loaded(engine, "pair-mixed")
    from datetime import datetime, timezone

    from event_ops_engine.facts import registration_facts
    from event_ops_engine.model import Member, Registration

    extra = Registration(
        id="m9",
        session="s2",
        members=(Member(gender="male", birth_year=1995),),
        status_events=({"at": datetime(2026, 11, 1, tzinfo=timezone.utc), "status": "confirmed"},),
    )
    engine.load(registration_facts(data, extra))  # female 3, male 2: diff 1 == max_diff
    assert caps(session_promotion(engine, "s2")) == {}


def test_capped_value_is_not_promoted_even_with_its_own_gap(engine: Engine) -> None:
    loaded(engine, "pair-mixed")  # female lo 6 but only 3 confirmed: a gap, yet capped
    decisions = session_promotion(engine, "s2")
    female = [d for d in decisions if (d.dim, d.value) == ("gender", "female")]
    assert [d.kind for d in female] == ["cap"]


# --- promotion cutoff (#52): stops `promote` only, inclusive, needs a start time ---------


def at_time(name: str, session_id: str, now: str, **update: object) -> list[Decision]:
    """Decisions for one session with `now` and session fields replaced."""
    from datetime import datetime

    base = scenario(name)
    sessions = tuple(
        s.model_copy(update=update) if s.id == session_id else s for s in base.sessions
    )
    data = base.model_copy(update={"now": datetime.fromisoformat(now), "sessions": sessions})
    return [d for d in promotion_decisions(data) if d.session == session_id]


def test_promotion_stops_at_the_cutoff_inclusive_but_cap_stays() -> None:
    from datetime import time

    start = {"start_time": time(19, 0)}  # s2 on 2026-11-10: cutoff 17:00
    before = at_time("pair-mixed", "s2", "2026-11-10T16:59:59+09:00", **start)
    male = by_value(before)[("gender", "male")]
    assert male.kind == "recommend" and "imbalance" in male.reasons
    assert {"promotion_cutoff_ts/s2", "now"} <= set(male.evidence)
    assert "시작 시각" not in male.message

    after = at_time("pair-mixed", "s2", "2026-11-10T17:00:00+09:00", **start)
    assert [d.kind for d in after] == ["cap"]  # female still capped; no recommendation


def test_full_session_keeps_its_hold_after_the_cutoff() -> None:
    from datetime import time

    decisions = at_time("ratio", "s4b", "2026-12-07T12:00:00+09:00", start_time=time(13, 0))
    assert {d.kind for d in decisions} == {"hold"}


def test_session_lead_days_zero_overrides_the_policy() -> None:
    decisions = at_time("pair-mixed", "s2", "2026-11-07T10:00:00+09:00", lead_days=0)
    assert by_value(decisions)[("gender", "male")].reasons == ("imbalance", "slow_trend")


def test_without_start_time_recommendations_flag_a_possibly_passed_cutoff() -> None:
    # No start time: the cutoff may fall as early as 2026-11-09 22:00 (midnight - 2 h).
    quiet = at_time("pair-mixed", "s2", "2026-11-09T21:59:59+09:00")
    assert all("시작 시각" not in d.message for d in quiet)
    flagged = by_value(at_time("pair-mixed", "s2", "2026-11-09T22:00:00+09:00"))
    male = flagged[("gender", "male")]
    assert male.kind == "recommend"  # still judged by date, as before #52
    assert "홍보 중단(시작 2시간 전)" in male.message
    assert "policy/s2/promotion_cutoff_hours" in male.evidence
