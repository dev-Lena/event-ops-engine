"""Layer: lib. Reads policy and scenario YAML files into validated models."""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import yaml

from .model import EventPolicy, Scenario, TriageScenario


class InputWarning(UserWarning):
    """The input still loads, but the next release refuses it."""


_INT, _FLOAT, _BOOL = (f"tag:yaml.org,2002:{name}" for name in ("int", "float", "bool"))


def _fields(node: yaml.Node | None) -> dict[str, yaml.Node]:
    if not isinstance(node, yaml.MappingNode):
        return {}
    return {key.value: value for key, value in node.value if isinstance(key, yaml.ScalarNode)}


def _reread(node: yaml.Node, loader: yaml.SafeLoader) -> str | None:
    """What YAML 1.1 made of an unquoted scalar, when that isn't what was typed: `014` is
    the number 12 (octal), `12:30` is 750 (base 60), `yes` is a boolean."""
    if not isinstance(node, yaml.ScalarNode) or node.tag not in (_INT, _FLOAT, _BOOL):
        return None
    value = loader.construct_object(node)
    if node.tag == _BOOL:
        text = "true" if value else "false"
        return None if node.value.lower() == text else f"the boolean {text}"
    if node.tag == _INT and node.value == str(value):
        return None
    return f"the number {value:g}" if node.tag == _FLOAT else f"the number {value}"


def _warn_reread_log_attrs(root: yaml.Node | None, loader: yaml.SafeLoader, path: Path) -> None:
    """Log attrs are matched as text by the rules, so a value YAML rereads changes the
    verdict without any error (#102). Warned for one release, then refused."""
    log = _fields(root).get("log")
    for event in log.value if isinstance(log, yaml.SequenceNode) else ():
        fields = _fields(event)
        id_node = fields.get("id")
        event_id = id_node.value if isinstance(id_node, yaml.ScalarNode) else "?"
        for key, node in _fields(fields.get("attrs")).items():
            reread = _reread(node, loader)
            if reread is not None:
                warnings.warn(
                    f"{path}: log event {event_id}, attrs.{key}: unquoted {node.value} is read "
                    f'as {reread}; quote it ("{node.value}") to keep the text. '
                    "The next release refuses it.",
                    InputWarning,
                    stacklevel=2,
                )


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        loader = yaml.SafeLoader(handle)
        try:
            root = loader.get_single_node()
            data = None if root is None else loader.construct_document(root)
            _warn_reread_log_attrs(root, loader, path)
        finally:
            loader.dispose()
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
