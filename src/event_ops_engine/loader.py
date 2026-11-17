"""Layer: lib. Reads policy and scenario YAML files into validated models."""

from __future__ import annotations

import re
import warnings
from pathlib import Path
from typing import Any

import yaml

from .model import EventPolicy, Scenario, TriageScenario

SAMPLE_SCENARIOS = Path("data") / "synthetic" / "scenarios"


def samples_dir() -> Path:
    """The synthetic sample scenarios (#110): `samples/` inside an installed package, else
    the checkout's own `data/synthetic/scenarios`. Triage samples sit in its `triage/`."""
    here = Path(__file__).resolve()
    for root in (here.parent / "samples", here.parents[2]):
        candidate = root / SAMPLE_SCENARIOS
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(
        "합성 예시 폴더를 찾지 못했습니다. 저장소를 받아 그 폴더에서 실행하거나 패키지를 다시 설치하세요."
    )


class InputWarning(UserWarning):
    """The input still loads, but the next release refuses it."""


_NUMBER_TAGS = ("tag:yaml.org,2002:int", "tag:yaml.org,2002:float")
_BOOL_TAG = "tag:yaml.org,2002:bool"
_PLAIN_INT = re.compile(r"-?(0|[1-9][0-9]*)")


def _fields(node: yaml.Node | None) -> dict[str, yaml.Node]:
    if not isinstance(node, yaml.MappingNode):
        return {}
    return {key.value: value for key, value in node.value if isinstance(key, yaml.ScalarNode)}


def _reread(node: yaml.Node) -> str | None:
    """How YAML 1.1 reads a scalar when that isn't what was typed, and what to write instead:
    `014` is the number 12 (octal), `12:30` is 750 (base 60), `yes` is a boolean.

    The value itself is left out: log attrs are free text, and warnings may end up in logs."""
    if not isinstance(node, yaml.ScalarNode):
        return None
    text = node.value.lower()
    if node.tag == _BOOL_TAG and text not in ("true", "false"):
        value = "true" if yaml.SafeLoader.bool_values[text] else "false"
        return f"the boolean {value}; write true or false, or quote it if it is text"
    if node.tag in _NUMBER_TAGS and not _PLAIN_INT.fullmatch(text):
        return (
            "a number, not the text typed (a leading 0 means octal, a colon means base 60); "
            "quote it to keep the text"
        )
    return None


def _warn_reread_log_attrs(root: yaml.Node | None, path: Path) -> None:
    """Log attrs are matched as text by the rules, so a value YAML rereads changes the
    verdict without any error (#102). Warned for one release, then refused."""
    log = _fields(root).get("log")
    for event in log.value if isinstance(log, yaml.SequenceNode) else ():
        fields = _fields(event)
        id_node = fields.get("id")
        event_id = id_node.value if isinstance(id_node, yaml.ScalarNode) else "?"
        for key, node in _fields(fields.get("attrs")).items():
            reread = _reread(node)
            if reread is not None:
                warnings.warn(
                    f"{path}: log event {event_id}, attrs.{key}: YAML reads this value as "
                    f"{reread}. The next release refuses it.",
                    InputWarning,
                    stacklevel=2,
                )


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        loader = yaml.SafeLoader(handle)
        try:
            root = loader.get_single_node()
            data = None if root is None else loader.construct_document(root)
            _warn_reread_log_attrs(root, path)
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
