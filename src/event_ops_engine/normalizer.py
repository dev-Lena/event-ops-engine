"""Layer: services. Free text → `job_group` candidate (docs/design.md 14).

The normalizer proposes a category, a confidence and the words it relied on. It never
decides: `facts.py` turns the proposal into a `candidate_attr` row and `rules/capacity.dl`
promotes it only above the policy's threshold. Two implementations, as for module ①:
`ClaudeCliNormalizer` (`claude -p`, no API cost) and `FakeNormalizer` (canned answers).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import ValidationError

from .facts import DIM_JOB_GROUP
from .interpreter import InterpretationError, Runner, json_object, run_subprocess
from .model import UNKNOWN, Member, NormalizedValue, Registration, Scenario

ScenarioT = TypeVar("ScenarioT", bound=Scenario)


class NormalizationError(Exception):
    """The normalizer produced nothing usable. `normalize_members` falls back to unknown."""


@dataclass(frozen=True)
class NormalizeContext:
    dim: str
    values: tuple[str, ...]


class Normalizer(Protocol):
    def normalize(self, text: str, context: NormalizeContext) -> NormalizedValue: ...


class FakeNormalizer:
    """Answers from a fixed table keyed by the input text. Tests and synthetic data only."""

    def __init__(self, canned: Mapping[str, NormalizedValue]) -> None:
        self.canned = dict(canned)

    @classmethod
    def from_scenario(cls, scenario: Scenario) -> FakeNormalizer:
        return cls(scenario.canned_job_groups)

    def normalize(self, text: str, context: NormalizeContext) -> NormalizedValue:
        try:
            return self.canned[text]
        except KeyError:
            raise NormalizationError(f"no canned answer for {text!r}") from None


def build_normalize_prompt(text: str, context: NormalizeContext) -> str:
    return "\n".join(
        [
            f"Map a free-text job description to one {context.dim} category. Answer with one",
            'JSON object and nothing else: {"value": "...", "confidence": 0.0, "quote": "..."}',
            f"Allowed values: {', '.join(context.values)}. Use another word only if none fits;",
            "it will then be reviewed by a person.",
            "`quote` must be copied verbatim from the text. confidence is between 0 and 1;",
            "give a low value when the text is vague or names several roles.",
            "",
            "Text:",
            text,
        ]
    )


def parse_normalized(raw: str) -> NormalizedValue:
    try:
        return NormalizedValue.model_validate(json_object(raw))
    except (ValueError, ValidationError) as error:
        raise NormalizationError(f"normalizer output does not match the schema: {error}") from error


class ClaudeCliNormalizer:
    """Runs the Claude Code CLI in print mode. No API key; uses the user's subscription."""

    def __init__(
        self, command: Sequence[str] = ("claude", "-p"), run: Runner = run_subprocess
    ) -> None:
        self.command = tuple(command)
        self.run = run

    def normalize(self, text: str, context: NormalizeContext) -> NormalizedValue:
        try:
            raw = self.run(self.command, build_normalize_prompt(text, context))
        except InterpretationError as error:
            raise NormalizationError(str(error)) from error
        return parse_normalized(raw)


NormalizerFactory = Callable[[Scenario], Normalizer]
NORMALIZERS: dict[str, NormalizerFactory] = {
    "fake": FakeNormalizer.from_scenario,
    "claude": lambda _scenario: ClaudeCliNormalizer(),
}


def _squash(text: str) -> str:
    return " ".join(text.split())


def normalize_member(member: Member, normalizer: Normalizer, context: NormalizeContext) -> Member:
    """The member with `job_group` filled. A failed or unquotable answer becomes unknown/0."""
    if member.job is None or member.job_group is not None:
        return member
    try:
        answer = normalizer.normalize(member.job, context)
        if _squash(answer.quote) not in _squash(member.job):
            raise NormalizationError("quote not found in the job text")
    except NormalizationError:
        answer = NormalizedValue(value=UNKNOWN, confidence=0.0, quote=member.job)
    return member.model_copy(update={"job_group": answer})


def normalize_members(scenario: ScenarioT, normalizer: Normalizer) -> ScenarioT:
    """The scenario with every member's job text normalized; unchanged without a job_group dim."""
    dimension = scenario.policy.dimensions.job_group
    if dimension is None:
        return scenario
    context = NormalizeContext(DIM_JOB_GROUP, dimension.values)
    registrations: list[Registration] = []
    for registration in scenario.registrations:
        if registration.members is None:
            registrations.append(registration)
            continue
        members = tuple(normalize_member(m, normalizer, context) for m in registration.members)
        registrations.append(registration.model_copy(update={"members": members}))
    return scenario.model_copy(update={"registrations": tuple(registrations)})
