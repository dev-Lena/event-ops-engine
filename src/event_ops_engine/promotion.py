"""Layer: features. Module ③ promotion judgement. Recommends only; people execute."""

from __future__ import annotations

from collections import defaultdict

from .decision import Decision, DecisionKind, DecisionPart
from .engine import Engine, contributors_by_value, unique
from .facts import evidence_id, scenario_facts
from .model import DIM_COMBO, DIM_GENDER, Scenario, combo_label

REASON_MESSAGES = {
    "lead_time": "회차 임박: {value} {need}명 부족, 홍보가 필요합니다.",
    "slow_trend": "신청 추세 느림: {value} {need}명 부족, 홍보를 권합니다.",
    "imbalance": "비율 불균형: {value} 쪽이 {need}명 적습니다.",
    "session_full": "정원 마감: {value} {need}명 부족이 남았지만 자리가 없습니다. 운영자 확인이 필요합니다.",
    "gender_room": (
        "목표 충돌: {value} 조합 부족 합 {need}명({parts})이 {value} 남은 자리 {room}명보다 "
        "많습니다. 조합 목표나 {value} 목표를 운영자가 확인해 주세요."
    ),
}

REASON_PRIORITY = ("lead_time", "slow_trend", "imbalance", "session_full", "gender_room")
"""The first reason present supplies `need` and the message. Gap-based reasons come first
because their number is the target shortfall; `imbalance` carries a ratio difference."""

GAP_REASONS = frozenset({"lead_time", "slow_trend", "session_full", "gender_room"})
"""Reasons whose `need` is a target shortfall (people), unlike `imbalance` (a difference)."""

REASON_POLICY_KEY = {"lead_time": "lead_days", "slow_trend": "trend_min_per_week"}

CUTOFF_UNKNOWN_NOTE = (
    " 회차 시작 시각이 없어 홍보 중단(시작 {hours}시간 전)이 지났는지 확인하지 못했습니다."
)


def cutoff_hours(engine: Engine, session_id: str) -> int:
    return int(engine.rows("policy", session_id, "promotion_cutoff_hours")[0][2])


def promotion_stopped(engine: Engine, session_id: str) -> bool:
    """True once the session's promotion cutoff has passed (#52): no `promote` rows remain."""
    return bool(engine.rows("past_cutoff", session_id))


def _cutoff_evidence(engine: Engine, session_id: str) -> tuple[list[str], str]:
    """Evidence and message note a recommendation carries about the promotion cutoff."""
    if engine.rows("promotion_cutoff_ts", session_id):
        return [evidence_id("promotion_cutoff_ts", session_id), evidence_id("now")], ""
    if engine.rows("cutoff_unknown", session_id):
        note = CUTOFF_UNKNOWN_NOTE.format(hours=cutoff_hours(engine, session_id))
        ids = [evidence_id("earliest_cutoff_ts", session_id), evidence_id("now")]
        return ids + [evidence_id("policy", session_id, "promotion_cutoff_hours")], note
    return [], ""


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


def _parts(
    engine: Engine,
    session_id: str,
    by_combo: dict[str, dict[str, int]],
    contributors: dict[tuple[str, str], list[str]],
) -> tuple[list[DecisionPart], list[str]]:
    """A gender's combinations (#32) as decision parts, youngest first, and their evidence."""
    ranges = {
        str(row[1]): (str(row[2]), int(row[3]), int(row[4]))
        for row in engine.rows("combo_def", session_id)
    }
    parts: list[DecisionPart] = []
    evidence: list[str] = []
    for combo in sorted(by_combo, key=lambda name: ranges[name][1:]):
        reasons = sorted(by_combo[combo])
        parts.append(
            DecisionPart(
                dim=DIM_COMBO,
                value=combo,
                label=combo_label(*ranges[combo]),
                need=max(by_combo[combo].values()),
                reasons=tuple(reasons),
            )
        )
        evidence += _evidence(engine, session_id, DIM_COMBO, combo, reasons, contributors)
        evidence.append(evidence_id("combo_def", session_id, combo))
    return parts, evidence


def _message(
    primary: str, value: str, need: int, room: int | None, parts: list[DecisionPart], own: bool
) -> str:
    """The decision sentence. A gender's line names its combinations as ad targets (#32);
    combinations alone (the gender itself has no shortfall) are named directly."""
    named_directly = parts and not own and primary != "gender_room"
    shown = " · ".join(part.label for part in parts) if named_directly else value
    listed = ", ".join(f"{part.label} {part.need}명" for part in parts)
    text = REASON_MESSAGES[primary].format(value=shown, need=need, room=room, parts=listed)
    if parts and primary in ("lead_time", "slow_trend") and (own or len(parts) > 1):
        targets = ", ".join(f"{part.label} {part.need}명 이상" for part in parts)
        text += f" 광고 대상: {targets}."
    return text


def _decisions(
    engine: Engine, session_id: str, relation: str, kind: DecisionKind
) -> list[Decision]:
    """One decision per (dim, value); combinations fold into their gender's decision (#32).

    A gender's `need` with combinations is the larger of its own shortfall and the sum of its
    combinations' shortfalls: everyone counted in a combination counts toward the gender too.
    Only combinations the rules recommended (or held) take part.
    """
    gender_of = {str(row[1]): str(row[2]) for row in engine.rows("combo_def", session_id)}
    grouped: dict[tuple[str, str], dict[str, int]] = defaultdict(dict)
    combos: dict[str, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(dict))
    for row in engine.rows(relation, session_id):
        dim, value, need, reason = str(row[1]), str(row[2]), int(row[3]), str(row[4])
        if dim == DIM_COMBO:
            by_reason = combos[gender_of[value]][value]
        else:
            by_reason = grouped[(dim, value)]
        by_reason[reason] = max(need, by_reason.get(reason, need))
    for gender in combos:
        grouped.setdefault((DIM_GENDER, gender), {})
    contributors = contributors_by_value(engine, session_id)
    cutoff_ids, note = _cutoff_evidence(engine, session_id) if relation == "promote" else ([], "")
    decisions: list[Decision] = []
    for (dim, value), own in sorted(grouped.items()):
        parts, part_evidence = (
            _parts(engine, session_id, combos[value], contributors)
            if dim == DIM_GENDER and value in combos
            else ([], [])
        )
        reasons = sorted(set(own) | {reason for part in parts for reason in part.reasons})
        primary = next(reason for reason in REASON_PRIORITY if reason in reasons)
        if parts:
            own_gap = max((n for reason, n in own.items() if reason in GAP_REASONS), default=0)
            need = max(own_gap, sum(part.need for part in parts))
        else:
            need = own[primary]
        room_rows = engine.rows("gender_room", session_id, value) if parts else []
        room = int(room_rows[0][2]) if room_rows else None
        evidence = _evidence(engine, session_id, dim, value, sorted(own), contributors)
        evidence += part_evidence + cutoff_ids
        decisions.append(
            Decision(
                kind=kind,
                session=session_id,
                dim=dim,
                value=value,
                need=need,
                reasons=tuple(reasons),
                evidence=tuple(unique(evidence)),
                message=_message(primary, value, need, room, parts, bool(own)) + note,
                parts=tuple(parts),
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
