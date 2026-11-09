"""Layer: features. Module ② capacity status: headcount against targets per session."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .decision import Decision, DecisionKind
from .engine import Engine, contributors_by_value
from .facts import evidence_id, scenario_facts
from .model import DIM_COMBO, Scenario


@dataclass(frozen=True)
class ValueStatus:
    dim: str
    value: str
    lo: int | None
    hi: int | None
    filled: int
    pending: int
    gap: int
    remaining: int | None
    is_full: bool
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class SessionStatus:
    session: str
    capacity: int
    filled: int
    pending: int
    remaining_seats: int
    is_full: bool
    values: tuple[ValueStatus, ...]
    needs_review: tuple[Decision, ...]


def _single_int(engine: Engine, relation: str, *key: str) -> int:
    rows = engine.rows(relation, *key)
    if len(rows) != 1:
        raise RuntimeError(f"{relation}{key}: expected one row, got {rows}")
    return int(rows[0][len(key)])


REVIEW_MESSAGES = {
    "unknown_party": "신청 {reg}: 인원 구성이 미상입니다. 참가자 성별·출생 연도를 확인해 주세요.",
    "low_confidence": "신청 {reg}: 직군 정규화 확신도가 기준 미만입니다. 직군을 확인해 주세요.",
    "unknown_value": "신청 {reg}: 정규화된 직군 값이 정책 목록에 없습니다. 직군을 확인해 주세요.",
    "missing_birth_year": (
        "신청 {reg}: 출생연도가 없거나 회차 연도보다 늦은 참가자가 있습니다(필수 항목). "
        "나이 집계에서 빠졌으니 출생연도를 확인해 주세요."
    ),
}


def rejected_candidates(engine: Engine) -> dict[str, list[str]]:
    """Evidence ids of candidates the rules did not promote, per registration."""
    promoted = {(str(row[0]), str(row[1])): str(row[2]) for row in engine.snapshot("attendee_attr")}
    rejected: dict[str, list[str]] = defaultdict(list)
    for attendee, dim, value, _confidence, evidence in engine.snapshot("candidate_attr"):
        if promoted.get((str(attendee), str(dim))) != str(value):
            rejected[str(attendee).split("#")[0]].append(str(evidence))
    return rejected


def missing_ages(engine: Engine) -> dict[str, list[str]]:
    """Evidence ids of attendees without a birth year (#32), per registration."""
    found: dict[str, list[str]] = defaultdict(list)
    for (attendee,) in engine.snapshot("age_missing"):
        found[str(attendee).split("#")[0]].append(evidence_id("age_missing", attendee))
    return found


def _review(
    session_id: str,
    reg: str,
    reason: str,
    rejected: dict[str, list[str]],
    missing: dict[str, list[str]],
) -> Decision:
    """One `needs_review` row as a Decision; evidence names the facts the rule looked at."""
    evidence = [evidence_id("registration", reg)]
    if reason == "unknown_party":
        evidence.append(evidence_id("unknown_party", reg))
    elif reason == "missing_birth_year":
        evidence.extend(missing.get(reg, []))
    else:
        evidence.extend(rejected.get(reg, []))
    return Decision(
        kind=DecisionKind.ASK,
        session=session_id,
        reasons=(reason,),
        evidence=tuple(evidence),
        message=REVIEW_MESSAGES.get(reason, "신청 {reg}: 확인이 필요합니다 ({reason}).").format(
            reg=reg, reason=reason
        ),
    )


def session_status(engine: Engine, session_id: str) -> SessionStatus:
    capacity = _single_int(engine, "session_capacity", session_id)
    targets = {
        (row[1], row[2]): (int(row[3]), int(row[4])) for row in engine.rows("target", session_id)
    }
    full_values = {(row[1], row[2]) for row in engine.rows("full", session_id)}
    gaps = {(row[1], row[2]): int(row[3]) for row in engine.rows("gap", session_id)}
    remaining = {(row[1], row[2]): int(row[3]) for row in engine.rows("remaining", session_id)}
    pending = {(row[1], row[2]): int(row[3]) for row in engine.rows("pending", session_id)}
    contributors = contributors_by_value(engine, session_id)

    values: list[ValueStatus] = []
    for row in engine.rows("filled", session_id):
        dim, value, filled = str(row[1]), str(row[2]), int(row[3])
        lo_hi = targets.get((dim, value))
        evidence = [evidence_id("target", session_id, dim, value)] if lo_hi else []
        if dim == DIM_COMBO:
            evidence.append(evidence_id("combo_def", session_id, value))
        evidence.append(evidence_id("session_capacity", session_id))
        evidence.extend(
            evidence_id("registration", reg) for reg in contributors.get((dim, value), [])
        )
        values.append(
            ValueStatus(
                dim=dim,
                value=value,
                lo=lo_hi[0] if lo_hi else None,
                hi=lo_hi[1] if lo_hi else None,
                filled=filled,
                pending=pending.get((dim, value), 0),
                gap=gaps.get((dim, value), 0),
                remaining=remaining.get((dim, value)),
                is_full=(dim, value) in full_values,
                evidence=tuple(evidence),
            )
        )

    rejected = rejected_candidates(engine)
    missing = missing_ages(engine)
    reviews = tuple(
        _review(session_id, str(row[1]), str(row[2]), rejected, missing)
        for row in engine.rows("needs_review", session_id)
    )
    return SessionStatus(
        session=session_id,
        capacity=capacity,
        filled=_single_int(engine, "session_filled", session_id),
        pending=_single_int(engine, "session_pending", session_id),
        remaining_seats=_single_int(engine, "remaining_seats", session_id),
        is_full=bool(engine.rows("session_full", session_id)),
        values=tuple(values),
        needs_review=reviews,
    )


def capacity_status(scenario: Scenario, engine: Engine | None = None) -> list[SessionStatus]:
    """Load the scenario (unless an engine is supplied) and report every session.

    Job texts must already be normalized (`normalizer.normalize_members`); unnormalized
    members count as `unknown` in the job_group dimension.
    """
    if engine is None:
        with Engine() as own:
            own.load(scenario_facts(scenario))
            return [session_status(own, session.id) for session in scenario.sessions]
    return [session_status(engine, session.id) for session in scenario.sessions]
