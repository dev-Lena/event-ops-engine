"""Time `report` and `triage` on seeded synthetic sign-ups (#34). Run: `make bench`.

Prints a markdown table (median of RUNS runs per shape) for docs/design.md 11.
Intel Mac: WIRELOG_LIB or the vendor build is picked up as in the tests.
"""

from __future__ import annotations

import platform
import statistics
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from event_ops_engine.capacity import capacity_status
from event_ops_engine.engine import Engine
from event_ops_engine.facts import scenario_facts
from event_ops_engine.harness import run_triage
from event_ops_engine.interpreter import FakeInterpreter
from event_ops_engine.loader import load_policy, load_triage_scenario
from event_ops_engine.model import Scenario
from event_ops_engine.promotion import promotion_decisions
from event_ops_engine.synthetic import generate

REPO = Path(__file__).resolve().parents[1]
POLICY = REPO / "policy" / "events" / "synthetic-example.yaml"
TRIAGE = REPO / "data" / "synthetic" / "scenarios" / "triage" / "account-length.yaml"
RUNS = 3
SHAPES = ((5, 20), (15, 20), (50, 20), (150, 20), (1, 300), (1, 1000))
"""(sessions, registrations per session): ~20 per session as in the real configs, then one
oversized session."""

T = TypeVar("T")


def timed(step: Callable[[], T]) -> tuple[T, float]:
    start = time.perf_counter()
    result = step()
    return result, time.perf_counter() - start


def report_once(scenario: Scenario) -> tuple[int, list[float]]:
    facts, t_facts = timed(lambda: scenario_facts(scenario))
    with Engine() as engine:
        _, t_load = timed(lambda: engine.load(facts))
        _, t_status = timed(lambda: capacity_status(scenario, engine))
        _, t_promo = timed(lambda: promotion_decisions(scenario, engine))
    rows = sum(len(r) for r in facts.rows.values())
    return rows, [t_facts, t_load, t_status, t_promo]


def triage_once(registrations: int) -> float:
    base = load_triage_scenario(TRIAGE)
    session = base.sessions[0]
    filler = generate(base.policy, 1, registrations, capacity=registrations * 4).registrations
    extra = tuple(r.model_copy(update={"session": session.id}) for r in filler)
    big = base.model_copy(
        update={
            "sessions": (session.model_copy(update={"capacity": registrations * 4}),),
            "registrations": base.registrations + extra,
        }
    )
    verdict, seconds = timed(lambda: run_triage(big, FakeInterpreter()))
    expected = base.expected.kind if base.expected else verdict.kind
    if verdict.kind != expected:
        sys.exit(f"triage verdict changed at {registrations} registrations: {verdict.kind}")
    return seconds


def main() -> None:
    policy = load_policy(POLICY)
    print(f"python {platform.python_version()} · {platform.system()} {platform.machine()}")
    print(
        "\n| 회차 × 신청 | 신청 | 참가자 | 사실 행 | 사실 만들기 | 엔진 적재 | 현황 | 홍보 | 합계 |"
    )
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for sessions, per_session in SHAPES:
        scenario = generate(policy, sessions, per_session)
        attendees = sum(r.party_size for r in scenario.registrations)
        runs = [report_once(scenario) for _ in range(RUNS)]
        rows = runs[0][0]
        stages = [statistics.median(run[1][i] for run in runs) for i in range(4)]
        cells = " | ".join(f"{s:.3f}s" for s in stages)
        print(
            f"| {sessions} × {per_session} | {len(scenario.registrations)} | {attendees} | "
            f"{rows} | {cells} | {sum(stages):.3f}s |"
        )
    print("\n| 문의 1건 + 같은 회차 신청 | 판정 시간 |")
    print("|---:|---:|")
    for registrations in (100, 300, 1000):
        seconds = statistics.median(triage_once(registrations) for _ in range(RUNS))
        print(f"| {registrations} | {seconds:.3f}s |")


if __name__ == "__main__":
    main()
