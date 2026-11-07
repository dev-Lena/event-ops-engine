"""Layer: lib. Seeded synthetic sign-ups for load measurement (#34). No real person or event.

The mix follows the shapes the rules care about: single, mixed pair, same-gender pair and
unknown composition, each moving through applied -> pending_payment -> confirmed / cancelled.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import TypeVar

from .model import EventPolicy, Gender, Member, Registration, Scenario, Session, Status, StatusEvent

T = TypeVar("T")

NOW = datetime.fromisoformat("2026-11-07T10:00:00+09:00")

PARTY_MIX = (("single", 60), ("mixed_pair", 25), ("same_pair", 10), ("unknown", 5))
"""Share (%) of each registration shape."""
FINAL_STATUS_MIX = (
    (Status.CONFIRMED, 60),
    (Status.PENDING_PAYMENT, 15),
    (Status.CANCELLED, 15),
    (Status.APPLIED, 10),
)
"""Share (%) of the status each registration ends in."""
PATH = {
    Status.APPLIED: (Status.APPLIED,),
    Status.PENDING_PAYMENT: (Status.APPLIED, Status.PENDING_PAYMENT),
    Status.CONFIRMED: (Status.APPLIED, Status.PENDING_PAYMENT, Status.CONFIRMED),
    Status.CANCELLED: (Status.APPLIED, Status.PENDING_PAYMENT, Status.CANCELLED),
}


def _pick(rng: random.Random, mix: tuple[tuple[T, int], ...]) -> T:
    return rng.choices([item for item, _ in mix], weights=[weight for _, weight in mix])[0]


def _member(rng: random.Random, gender: Gender) -> Member:
    return Member(gender=gender, birth_year=rng.randint(1980, 2003))


def _members(rng: random.Random, shape: str) -> tuple[Member, ...] | None:
    one = rng.choice((Gender.FEMALE, Gender.MALE))
    if shape == "single":
        return (_member(rng, one),)
    if shape == "mixed_pair":
        return (_member(rng, Gender.FEMALE), _member(rng, Gender.MALE))
    if shape == "same_pair":
        return (_member(rng, one), _member(rng, one))
    return None


def _registration(rng: random.Random, reg_id: str, session_id: str) -> Registration:
    shape = _pick(rng, PARTY_MIX)
    final = _pick(rng, FINAL_STATUS_MIX)
    # The last of up to three hourly steps still lands before `now`.
    start = NOW - timedelta(minutes=rng.randint(3 * 60, 30 * 24 * 60))
    events = tuple(
        StatusEvent(at=start + timedelta(hours=step), status=status)
        for step, status in enumerate(PATH[final])
    )
    members = _members(rng, shape)
    return Registration(
        id=reg_id,
        session=session_id,
        party_size=2 if members is None else len(members),
        members=members,
        status_events=events,
    )


def generate(
    policy: EventPolicy, sessions: int, per_session: int, seed: int = 0, capacity: int | None = None
) -> Scenario:
    """`sessions` sessions with `per_session` registrations each, all from one seed.

    Capacity defaults to twice the attendees a session could hold, so load is measured
    without every session being full; pass `capacity` to measure full sessions too.
    """
    rng = random.Random(seed)
    room = capacity if capacity is not None else max(per_session * 4, 12)
    session_rows = tuple(
        Session(id=f"s{i + 1}", date=(NOW + timedelta(days=1 + i % 30)).date(), capacity=room)
        for i in range(sessions)
    )
    registrations = tuple(
        _registration(rng, f"s{i + 1}r{j + 1}", f"s{i + 1}")
        for i in range(sessions)
        for j in range(per_session)
    )
    return Scenario(policy=policy, now=NOW, sessions=session_rows, registrations=registrations)
