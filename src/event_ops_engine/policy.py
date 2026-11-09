"""Layer: lib. Resolves per-session targets from an event policy plus session overrides."""

from __future__ import annotations

from .model import DIM_COMBO, DIM_GENDER, Combos, EventPolicy, Session, Targets, effective_combos

POLICY_KEYS = ("lead_days", "trend_min_per_week", "promotion_cutoff_hours")
"""Keys of the `policy(session, key, n)` relation; same names as PromotionPolicy fields."""
SESSION_POLICY_KEYS = ("lead_days", "promotion_cutoff_hours")
"""Promotion keys a session may override (#52), like `payment_deadline_hours`."""


def resolve_promotion(policy: EventPolicy, session: Session) -> dict[str, int]:
    """Promotion thresholds for one session. 0 is a real override, hence `is None`."""
    values: dict[str, int] = {key: getattr(policy.promotion, key) for key in POLICY_KEYS}
    for key in SESSION_POLICY_KEYS:
        override = getattr(session, key)
        if override is not None:
            values[key] = override
    return values


def resolve_targets(policy: EventPolicy, session: Session) -> list[tuple[str, str, int, int]]:
    """(dim, value, lo, hi) rows. Session targets replace the defaults for the dims they name.

    A single value's lo or hi above the capacity can never be met and is rejected. Lo values
    whose *sum* exceeds the capacity are allowed: that conflict is what `blocked` reports.
    """
    capacity = session.capacity or policy.defaults.capacity
    merged: Targets = dict(policy.defaults.targets)
    if session.targets is not None:
        merged.update(session.targets)
    rows: list[tuple[str, str, int, int]] = []
    for dim, by_value in merged.items():
        for value, target in by_value.items():
            hi = capacity if target.hi is None else target.hi
            if target.lo > capacity or hi > capacity:
                raise ValueError(
                    f"session {session.id}: target {dim}={value} ({target.lo}~{hi}) "
                    f"exceeds capacity {capacity}"
                )
            rows.append((dim, value, target.lo, hi))
    _check_combo_minimums(session.id, rows, resolve_combos(policy, session), capacity)
    return rows


def resolve_combos(policy: EventPolicy, session: Session) -> Combos:
    """The session's combinations (#32): event defaults plus the session's own, by id."""
    return effective_combos(policy.defaults.combos, session.combos)


def _check_combo_minimums(
    session_id: str, rows: list[tuple[str, str, int, int]], combos: Combos, capacity: int
) -> None:
    """A gender's combination minimums must fit under that gender's maximum (the capacity when
    unset): everyone counted in a combination is counted in the gender too, so a larger sum
    could never be met."""
    gender_hi = {value: hi for dim, value, _, hi in rows if dim == DIM_GENDER}
    minimums: dict[str, list[tuple[str, int]]] = {}
    for dim, value, lo, _ in rows:
        if dim == DIM_COMBO:
            minimums.setdefault(combos[value].gender.value, []).append((value, lo))
    for gender, items in sorted(minimums.items()):
        limit = gender_hi.get(gender, capacity)
        total = sum(lo for _, lo in items)
        if total > limit:
            named = ", ".join(f"{name} {lo}" for name, lo in items)
            raise ValueError(
                f"session {session_id}: combination minimums for {gender} ({named}) add up "
                f"to {total}, above the {gender} maximum {limit}"
            )


def resolve_ratios(policy: EventPolicy, session: Session) -> list[tuple[str, str, str, int]]:
    ratios = policy.defaults.ratios if session.ratios is None else session.ratios
    return [(ratio.dim, ratio.values[0], ratio.values[1], ratio.max_diff) for ratio in ratios]
