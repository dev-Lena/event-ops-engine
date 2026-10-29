"""Module ③ promotion judgement: reasons, holds, inactive sessions, evidence."""

from event_ops_engine.decision import Decision
from event_ops_engine.engine import Engine
from event_ops_engine.promotion import promotion_decisions, session_promotion
from tests.conftest import loaded, scenario


def by_value(decisions: list[Decision]) -> dict[tuple[str, str], Decision]:
    return {(d.dim or "", d.value or ""): d for d in decisions}


def test_slow_trend_and_imbalance_recommend_promotion(engine: Engine) -> None:
    loaded(engine, "single")  # 14 days left: outside lead_days
    decisions = by_value(session_promotion(engine, "s1"))
    assert {k for k, d in decisions.items() if d.kind == "recommend"} == {
        ("gender", "female"),
        ("gender", "male"),
        ("age_band", "20s"),
        ("age_band", "30s"),
    }
    assert decisions[("gender", "female")].reasons == ("slow_trend",)
    assert decisions[("gender", "male")].reasons == ("imbalance", "slow_trend")
    assert decisions[("gender", "male")].need == 5
    assert "lead_time" not in decisions[("gender", "female")].reasons


def test_lead_time_fires_inside_lead_days(engine: Engine) -> None:
    loaded(engine, "pair-mixed")  # 3 days left
    decisions = by_value(session_promotion(engine, "s2"))
    assert decisions[("gender", "female")].reasons == ("lead_time", "slow_trend")
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
