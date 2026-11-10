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


def _check_policy(data: Any, path: Path) -> Any:
    """`similar_age:` with nothing after it is YAML null, which would silently mean "off"
    (#91). Checked here, not in the model, so a dumped policy still validates."""
    if isinstance(data, dict) and "similar_age" in data and data["similar_age"] is None:
        raise ValueError(f"{path}: similar_age is blank; write `similar_age: {{}}` or remove it")
    return data


def load_policy(path: Path) -> EventPolicy:
    return EventPolicy.model_validate(_check_policy(_read_yaml(path), path))


def _scenario_data(path: Path) -> dict[str, Any]:
    """A scenario file names its policy file by a path relative to itself."""
    data = _read_yaml(path)
    policy_ref = data.get("policy")
    if isinstance(policy_ref, str):
        policy_path = (path.parent / policy_ref).resolve()
        data["policy"] = _check_policy(_read_yaml(policy_path), policy_path)
    else:
        _check_policy(policy_ref, path)
    return data


def load_scenario(path: Path) -> Scenario:
    return Scenario.model_validate(_scenario_data(path))


def load_triage_scenario(path: Path) -> TriageScenario:
    return TriageScenario.model_validate(_scenario_data(path))
