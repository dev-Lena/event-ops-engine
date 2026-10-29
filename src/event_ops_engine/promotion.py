"""Layer: features. Module ③ promotion judgement. Recommends only; people execute."""

from __future__ import annotations

from collections import defaultdict

from .decision import Decision, DecisionKind
from .engine import Engine, contributing_registrations, unique
from .facts import evidence_id, scenario_facts
from .model import Scenario

REASON_MESSAGES = {
    "lead_time": "회차 임박: {value} {need}명 부족, 홍보가 필요합니다.",
    "slow_trend": "신청 추세 느림: {value} {need}명 부족, 홍보를 권합니다.",
    "imbalance": "비율 불균형: {value} 쪽이 {need}명 적습니다.",
    "session_full": "정원 마감: {value} {need}명 부족이 남았지만 자리가 없습니다. 운영자 확인이 필요합니다.",
}

REASON_POLICY_KEY = {"lead_time": "lead_days", "slow_trend": "trend_min_per_week"}


def _evidence(
    engine: Engine, session_id: str, dim: str, value: str, reasons: list[str]
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
    ids.extend(
        evidence_id("registration", reg)
        for reg in contributing_registrations(engine, session_id, dim, value)
    )
    return unique(ids)


def _decisions(
    engine: Engine, session_id: str, relation: str, kind: DecisionKind
) -> list[Decision]:
    grouped: dict[tuple[str, str], list[tuple[int, str]]] = defaultdict(list)
    for row in engine.rows(relation, session_id):
        grouped[(str(row[1]), str(row[2]))].append((int(row[3]), str(row[4])))
    decisions: list[Decision] = []
    for (dim, value), items in sorted(grouped.items()):
        need = max(need for need, _ in items)
        reasons = sorted({reason for _, reason in items})
        first = REASON_MESSAGES[reasons[0]].format(value=value, need=need)
        decisions.append(
            Decision(
                kind=kind,
                session=session_id,
                dim=dim,
                value=value,
                need=need,
                reasons=tuple(reasons),
                evidence=tuple(_evidence(engine, session_id, dim, value, reasons)),
                message=first,
            )
        )
    return decisions


def session_promotion(engine: Engine, session_id: str) -> list[Decision]:
    return _decisions(engine, session_id, "promote", DecisionKind.RECOMMEND) + _decisions(
        engine, session_id, "blocked", DecisionKind.HOLD
    )


def promotion_decisions(scenario: Scenario, engine: Engine | None = None) -> list[Decision]:
    if engine is None:
        with Engine() as own:
            own.load(scenario_facts(scenario))
            return [d for s in scenario.sessions for d in session_promotion(own, s.id)]
    return [d for s in scenario.sessions for d in session_promotion(engine, s.id)]
