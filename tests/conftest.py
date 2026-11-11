"""Shared fixtures: repo paths, a scenario loader and a fresh engine per test.

The local engine build is picked up by `engine.ensure_library_env` when WIRELOG_LIB is unset.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from event_ops_engine.engine import Engine
from event_ops_engine.facts import scenario_facts
from event_ops_engine.loader import load_scenario
from event_ops_engine.model import Scenario

REPO = Path(__file__).resolve().parents[1]
SCENARIOS = REPO / "data" / "synthetic" / "scenarios"
POLICY = REPO / "policy" / "events" / "synthetic-example.yaml"


def scenario(name: str) -> Scenario:
    return load_scenario(SCENARIOS / f"{name}.yaml")


@pytest.fixture
def engine() -> Iterator[Engine]:
    with Engine() as instance:
        yield instance


def loaded(engine: Engine, name: str) -> Scenario:
    data = scenario(name)
    engine.load(scenario_facts(data))
    return data
