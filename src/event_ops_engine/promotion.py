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
    "session_full_ratio": (
        "정원 마감: {value} 확정 인원이 상대 쪽보다 {need}명 적습니다(비율 차). "
        "자리가 없어 홍보로 맞출 수 없으니 운영자 확인이 필요합니다."
    ),
    "gender_room": (
        "목표 충돌: {value} 조합 부족 합 {need}명({parts})이 {value} 남은 자리 {room}명보다 "
        "많습니다. 조합 목표나 {value} 목표를 운영자가 확인해 주세요."
    ),
}

GAP_REASONS = ("lead_time", "slow_trend", "session_full", "gender_room")
"""Reasons whose number is a target shortfall (`gap`)."""
RATIO_REASONS = ("imbalance", "session_full_ratio")
"""Reasons whose number is a ratio difference: never added to or shown as a shortfall."""
ROOM_BY_SESSION = (
    "목표 충돌: {value} 조합 부족 합 {need}명({parts})이 회차 남은 자리 {room}명보다 많습니다. "
    "조합 목표나 정원을 운영자가 확인해 주세요."
)
"""The `gender_room` sentence when the session's seats, not the gender's target, are the
limit (#107): it names the room that is actually short and what to revisit."""

REASON_PRIORITY = (
    "lead_time",
    "slow_trend",
    "imbalance",
    "session_full",
    "session_full_ratio",
    "gender_room",
)
"""The first reason present supplies the message. Within `promote` and within `blocked` the
gap-based reason comes before the ratio one, so a shortfall is named before a difference."""

RATIO_NOTE = " 비율 차도 있습니다: {value} 확정 인원이 상대 쪽보다 {diff}명 적습니다."
"""Appended to a shortfall hold that also carries a ratio difference (#106)."""

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
    if any(reason in RATIO_REASONS for reason in reasons):
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
    ranges: dict[str, tuple[str, int, int]],
    contributors: dict[tuple[str, str], list[str]],
) -> tuple[list[DecisionPart], list[str]]:
    """A gender's combinations (#32) as decision parts, youngest first, and their evidence.
    `ranges` maps a combination id to (gender, low, high) from `combo_def`."""
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
    primary: str,
    value: str,
    need: int,
    room: int | None,
    parts: list[DecisionPart],
    own: bool,
    by_session: bool = False,
) -> str:
    """The decision sentence. A gender's line names its combinations as ad targets (#32);
    combinations alone (the gender itself has no shortfall) are named directly. `by_session`
    says a `gender_room` conflict is limited by the session's seats (#107)."""
    named_directly = parts and not own and primary != "gender_room"
    shown = " · ".join(part.label for part in parts) if named_directly else value
    listed = ", ".join(f"{part.label} {part.need}명" for part in parts)
    session_room = primary == "gender_room" and by_session
    template = ROOM_BY_SESSION if session_room else REASON_MESSAGES[primary]
    text = template.format(value=shown, need=need, room=room, parts=listed)
    if parts and primary in ("lead_time", "slow_trend") and (own or len(parts) > 1):
        targets = ", ".join(f"{part.label} {part.need}명 이상" for part in parts)
        text += f" 광고 대상: {targets}."
    return text


def _decisions(
    engine: Engine, session_id: str, relation: str, kind: DecisionKind
) -> list[Decision]:
    """One decision per (dim, value); combinations fold into their gender's decision (#32).

    A gender's `shortfall` with combinations is the larger of its own shortfall and the sum
    of its combinations' shortfalls: everyone counted in a combination counts toward the
    gender too. Only combinations the rules recommended (or held) take part.

    `shortfall` and `ratio_diff` are kept apart (#106): `need` is the shortfall when there is
    one and the ratio difference only when nothing is short.
    """
    ranges = {
        str(row[1]): (str(row[2]), int(row[3]), int(row[4]))
        for row in engine.rows("combo_def", session_id)
    }
    grouped: dict[tuple[str, str], dict[str, int]] = defaultdict(dict)
    combos: dict[str, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(dict))
    for row in engine.rows(relation, session_id):
        dim, value, count, reason = str(row[1]), str(row[2]), int(row[3]), str(row[4])
        if dim == DIM_COMBO:
            by_reason = combos[ranges[value][0]][value]
        else:
            by_reason = grouped[(dim, value)]
        by_reason[reason] = max(count, by_reason.get(reason, count))
    for gender in combos:
        grouped.setdefault((DIM_GENDER, gender), {})
    contributors = contributors_by_value(engine, session_id)
    cutoff_ids, note = _cutoff_evidence(engine, session_id) if relation == "promote" else ([], "")
    decisions: list[Decision] = []
    for (dim, value), own in sorted(grouped.items()):
        parts, part_evidence = (
            _parts(engine, session_id, combos[value], ranges, contributors)
            if dim == DIM_GENDER and value in combos
            else ([], [])
        )
        reasons = sorted(set(own) | {reason for part in parts for reason in part.reasons})
        primary = next(reason for reason in REASON_PRIORITY if reason in reasons)
        ratio_diff = next((own[reason] for reason in RATIO_REASONS if reason in own), None)
        shortfall = next((own[reason] for reason in GAP_REASONS if reason in own), None)
        own_short = False
        if parts:
            # The gender's own shortfall comes from `gap`, whether or not the rules gave the
            # gender a gap-based reason of its own (it may be short without being slow).
            gap_rows = engine.rows("gap", session_id, dim, value)
            own_gap = int(gap_rows[0][3]) if gap_rows else 0
            own_short = own_gap > 0
            shortfall = max(own_gap, sum(part.need for part in parts))
        need = shortfall if shortfall is not None else ratio_diff
        if need is None:
            raise ValueError(f"{relation} reasons carry neither a gap nor a ratio: {reasons}")
        room, by_session = None, False
        if primary == "gender_room":
            room = int(engine.rows("gender_room", session_id, value)[0][2])
            # The room is the smaller of the gender's and the session's (#107); the session's
            # is the limit when it is smaller, or when the gender has no target of its own.
            own_room = engine.rows("remaining", session_id, dim, value)
            by_session = not own_room or room < int(own_room[0][3])
        if own or own_short or primary == "gender_room":
            # A conflict hold also rests on the gender's room: its target and its people. So
            # does a sentence that counts the gender's own shortfall.
            evidence = _evidence(engine, session_id, dim, value, sorted(own), contributors)
        else:
            evidence = [evidence_id("session_capacity", session_id)]
            evidence.append(evidence_id("days_left", session_id))
        evidence += part_evidence + cutoff_ids
        # The gender is named as short only when it has a shortfall of its own (`own_short`):
        # a ratio difference alone leaves the combinations to be named directly.
        message = _message(primary, value, need, room, parts, own_short, by_session) + note
        if kind is DecisionKind.HOLD and shortfall is not None and ratio_diff is not None:
            message += RATIO_NOTE.format(value=value, diff=ratio_diff)
        decisions.append(
            Decision(
                kind=kind,
                session=session_id,
                dim=dim,
                value=value,
                need=need,
                reasons=tuple(reasons),
                evidence=tuple(unique(evidence)),
                message=message,
                parts=tuple(parts),
                shortfall=shortfall,
                ratio_diff=ratio_diff,
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
