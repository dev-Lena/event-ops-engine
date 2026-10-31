"""Layer: lib. Reads policy and scenario YAML files into validated models."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .model import EventPolicy, Scenario, TriageScenario


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping at top level")
    return data


def load_policy(path: Path) -> EventPolicy:
    return EventPolicy.model_validate(_read_yaml(path))


def _scenario_data(path: Path) -> dict[str, Any]:
    """A scenario file names its policy file by a path relative to itself."""
    data = _read_yaml(path)
    policy_ref = data.get("policy")
    if isinstance(policy_ref, str):
        data["policy"] = _read_yaml((path.parent / policy_ref).resolve())
    return data


def load_scenario(path: Path) -> Scenario:
    return Scenario.model_validate(_scenario_data(path))


def load_triage_scenario(path: Path) -> TriageScenario:
    return TriageScenario.model_validate(_scenario_data(path))
