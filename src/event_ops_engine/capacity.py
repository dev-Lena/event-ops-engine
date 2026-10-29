"""Layer: features. Module ② capacity status: headcount against targets per session."""

from __future__ import annotations

from dataclasses import dataclass

from .decision import Decision, DecisionKind
from .engine import Engine, contributing_registrations
from .facts import evidence_id, scenario_facts
from .model import Scenario


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


def session_status(engine: Engine, session_id: str) -> SessionStatus:
    capacity = _single_int(engine, "session_capacity", session_id)
    targets = {
        (row[1], row[2]): (int(row[3]), int(row[4])) for row in engine.rows("target", session_id)
    }
    full_values = {(row[1], row[2]) for row in engine.rows("full", session_id)}
    gaps = {(row[1], row[2]): int(row[3]) for row in engine.rows("gap", session_id)}
    remaining = {(row[1], row[2]): int(row[3]) for row in engine.rows("remaining", session_id)}
    pending = {(row[1], row[2]): int(row[3]) for row in engine.rows("pending", session_id)}

    values: list[ValueStatus] = []
    for row in engine.rows("filled", session_id):
        dim, value, filled = str(row[1]), str(row[2]), int(row[3])
        lo_hi = targets.get((dim, value))
        evidence = [evidence_id("target", session_id, dim, value)] if lo_hi else []
        evidence.append(evidence_id("session_capacity", session_id))
        evidence.extend(
            evidence_id("registration", reg)
            for reg in contributing_registrations(engine, session_id, dim, value)
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

    reviews = tuple(
        Decision(
            kind=DecisionKind.ASK,
            session=session_id,
            reasons=(str(row[2]),),
            evidence=(evidence_id("registration", row[1]), evidence_id("unknown_party", row[1])),
            message=f"신청 {row[1]}: 인원 구성이 미상입니다. 참가자 성별·출생 연도를 확인해 주세요.",
        )
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
    """Load the scenario (unless an engine is supplied) and report every session."""
    if engine is None:
        with Engine() as own:
            own.load(scenario_facts(scenario))
            return [session_status(own, session.id) for session in scenario.sessions]
    return [session_status(engine, session.id) for session in scenario.sessions]
