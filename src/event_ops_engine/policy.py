"""Layer: lib. Resolves per-session targets from an event policy plus session overrides."""

from __future__ import annotations

from .model import EventPolicy, Session, Targets

POLICY_KEYS = ("lead_days", "trend_min_per_week")
"""Keys of the `policy(session, key, n)` relation; same names as PromotionPolicy fields."""


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
    return rows


def resolve_ratios(policy: EventPolicy, session: Session) -> list[tuple[str, str, str, int]]:
    ratios = policy.defaults.ratios if session.ratios is None else session.ratios
    return [(ratio.dim, ratio.values[0], ratio.values[1], ratio.max_diff) for ratio in ratios]
