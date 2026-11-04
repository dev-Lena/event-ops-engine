"""Layer: features. Module ③ promotion judgement. Recommends only; people execute."""

from __future__ import annotations

from collections import defaultdict

from .decision import Decision, DecisionKind
from .engine import Engine, contributors_by_value, unique
from .facts import evidence_id, scenario_facts
from .model import Scenario

REASON_MESSAGES = {
    "lead_time": "회차 임박: {value} {need}명 부족, 홍보가 필요합니다.",
    "slow_trend": "신청 추세 느림: {value} {need}명 부족, 홍보를 권합니다.",
    "imbalance": "비율 불균형: {value} 쪽이 {need}명 적습니다.",
    "session_full": "정원 마감: {value} {need}명 부족이 남았지만 자리가 없습니다. 운영자 확인이 필요합니다.",
}

REASON_PRIORITY = ("lead_time", "slow_trend", "imbalance", "session_full")
"""The first reason present supplies `need` and the message. Gap-based reasons come first
because their number is the target shortfall; `imbalance` carries a ratio difference."""

REASON_POLICY_KEY = {"lead_time": "lead_days", "slow_trend": "trend_min_per_week"}


def _evidence(
    engine: Engine,
    session_id: str,
    dim: str,
    value: str,
    reasons: list[str],
    contributors: dict[tuple[str, str], list[str]],
) -> list[str]:
    ids = [evidence_id("session_capacity", session_id), evidence_id("days_left", session_id)]
    if engine.rows("target", session_id, dim, value):
        ids.append(evidence_id("target", session_id, dim, value))
    if "imbalance" in reasons:
        ids.append(evidence_id("ratio_target", session_id, dim))
    for reason in reasons:
        key = REASON_POLICY_KEY.get(reason)
        if key:
            ids.append(evidence_id("policy", session_id, key))
    if "slow_trend" in reasons:
        ids.append(evidence_id("now"))
    ids.extend(evidence_id("registration", reg) for reg in contributors.get((dim, value), []))
    return unique(ids)


def _decisions(
    engine: Engine, session_id: str, relation: str, kind: DecisionKind
) -> list[Decision]:
    grouped: dict[tuple[str, str], dict[str, int]] = defaultdict(dict)
    for row in engine.rows(relation, session_id):
        by_reason = grouped[(str(row[1]), str(row[2]))]
        reason, need = str(row[4]), int(row[3])
        by_reason[reason] = max(need, by_reason.get(reason, need))
    contributors = contributors_by_value(engine, session_id)
    decisions: list[Decision] = []
    for (dim, value), by_reason in sorted(grouped.items()):
        primary = next(reason for reason in REASON_PRIORITY if reason in by_reason)
        need = by_reason[primary]
        reasons = sorted(by_reason)
        decisions.append(
            Decision(
                kind=kind,
                session=session_id,
                dim=dim,
                value=value,
                need=need,
                reasons=tuple(reasons),
                evidence=tuple(_evidence(engine, session_id, dim, value, reasons, contributors)),
                message=REASON_MESSAGES[primary].format(value=value, need=need),
            )
        )
    return decisions


CAP_MESSAGE = (
    "비율 조정: {value} 잠정 마감 권고. 확정 {filled}명이 {other} {other_filled}명보다 "
    "허용 차이 {max_diff}명을 넘었습니다. 상한 {limit}명으로 두고 {other} 쪽이 늘면 다시 엽니다."
)


def _cap_decisions(engine: Engine, session_id: str) -> list[Decision]:
    """One `cap` row per leading value (#51). `need` carries the recommended limit."""
    contributors = contributors_by_value(engine, session_id)
    decisions: list[Decision] = []
    for row in sorted(engine.rows("cap", session_id)):
        dim, value, limit, other, other_filled, max_diff = (
            str(row[1]),
            str(row[2]),
            int(row[3]),
            str(row[4]),
            int(row[5]),
            int(row[6]),
        )
        filled = int(engine.rows("filled", session_id, dim, value)[0][3])
        evidence = [evidence_id("ratio_target", session_id, dim)]
        for side in (value, other):
            evidence.extend(
                evidence_id("registration", r) for r in contributors.get((dim, side), [])
            )
        decisions.append(
            Decision(
                kind=DecisionKind.CAP,
                session=session_id,
                dim=dim,
                value=value,
                need=limit,
                reasons=("imbalance",),
                evidence=tuple(unique(evidence)),
                message=CAP_MESSAGE.format(
                    value=value,
                    filled=filled,
                    other=other,
                    other_filled=other_filled,
                    max_diff=max_diff,
                    limit=limit,
                ),
            )
        )
    return decisions


def session_promotion(engine: Engine, session_id: str) -> list[Decision]:
    return (
        _decisions(engine, session_id, "promote", DecisionKind.RECOMMEND)
        + _decisions(engine, session_id, "blocked", DecisionKind.HOLD)
        + _cap_decisions(engine, session_id)
    )


def promotion_decisions(scenario: Scenario, engine: Engine | None = None) -> list[Decision]:
    if engine is None:
        with Engine() as own:
            own.load(scenario_facts(scenario))
            return [d for s in scenario.sessions for d in session_promotion(own, s.id)]
    return [d for s in scenario.sessions for d in session_promotion(engine, s.id)]
