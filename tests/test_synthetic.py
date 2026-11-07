"""The load generator (#34): seeded, valid, and the rules count it the way plain Python does."""

from collections import Counter

from event_ops_engine.capacity import capacity_status
from event_ops_engine.engine import Engine
from event_ops_engine.facts import scenario_facts
from event_ops_engine.loader import load_policy
from event_ops_engine.model import Scenario, Status
from event_ops_engine.synthetic import generate
from tests.conftest import POLICY


def sample() -> Scenario:
    return generate(load_policy(POLICY), sessions=6, per_session=30, seed=7)


def test_same_seed_gives_the_same_scenario() -> None:
    assert sample() == sample()
    shapes = Counter(r.members is None for r in sample().registrations)
    assert shapes[True] > 0 and shapes[False] > 0  # unknown composition is in the mix
    latest = max(e.at for r in sample().registrations for e in r.status_events)
    assert latest < sample().now  # no history after the reference time


def test_rule_counts_match_a_python_count_at_load() -> None:
    data = sample()
    filled: Counter[str] = Counter()
    pending: Counter[str] = Counter()
    by_gender: Counter[tuple[str, str]] = Counter()
    for reg in data.registrations:
        status = max(reg.status_events, key=lambda event: event.at).status
        if status == Status.CONFIRMED:
            filled[reg.session] += reg.party_size
            for member in reg.members or ():
                by_gender[(reg.session, member.gender.value)] += 1
        elif status == Status.PENDING_PAYMENT:
            pending[reg.session] += reg.party_size
    with Engine() as engine:
        engine.load(scenario_facts(data))
        statuses = capacity_status(data, engine)
    assert len(statuses) == 6
    for status in statuses:
        assert status.filled == filled[status.session]
        assert status.pending == pending[status.session]
        genders = {v.value: v.filled for v in status.values if v.dim == "gender"}
        assert genders == {g: by_gender[(status.session, g)] for g in ("female", "male")}
