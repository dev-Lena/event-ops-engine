"""Layer: services. Free text → `job_group` candidate (docs/design.md 14).

The normalizer proposes a category, a confidence and the words it relied on. It never
decides: `facts.py` turns the proposal into a `candidate_attr` row and `rules/capacity.dl`
promotes it only above the policy's threshold. Two implementations, as for module ①:
`ClaudeCliNormalizer` (`claude -p`, no API cost) and `FakeNormalizer` (canned answers).

Before any LLM call, the policy's approved alias dictionary settles every text with exactly
one clear hit (#62). Each distinct remaining text is asked once, and the Claude CLI
normalizer asks for all of them in a single prompt (#63): one `claude -p` call costs close
to a minute.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import ValidationError

from .facts import DIM_JOB_GROUP, squash
from .interpreter import InterpretationError, Runner, json_object, run_subprocess
from .model import UNKNOWN, Member, NormalizedValue, Registration, Scenario

ScenarioT = TypeVar("ScenarioT", bound=Scenario)


class NormalizationError(Exception):
    """The normalizer produced nothing usable. `normalize_members` falls back to unknown."""


@dataclass(frozen=True)
class NormalizeContext:
    dim: str
    values: tuple[str, ...]
    aliases: tuple[tuple[str, tuple[str, ...]], ...] = ()
    """Approved words per value (policy `aliases`), in policy order."""


class Normalizer(Protocol):
    def normalize(self, text: str, context: NormalizeContext) -> NormalizedValue: ...


BATCH_SIZE = 40
"""Texts per Claude CLI prompt: keeps one prompt well inside the context and the timeout."""


def _find(word: str, text: str) -> int:
    """Start of `word` in `text` (case-insensitive), or -1. ASCII words must stand alone so
    "UX" does not match inside "luxury"; Korean words match anywhere ("백엔드 3년차")."""
    if word.isascii():
        found = re.search(rf"(?<![A-Za-z0-9]){re.escape(word)}(?![A-Za-z0-9])", text, re.I)
        return found.start() if found else -1
    return text.lower().find(word.lower())


def match_alias(text: str, context: NormalizeContext) -> NormalizedValue | None:
    """The settled value when exactly one value's approved words occur in the text.

    Only words a person put in the dictionary count, not the value names themselves. The
    quote is the matched word as written. No hit, or hits for several values ("마케팅 겸
    기획"), returns None and the text goes to the normalizer.
    """
    hits: dict[str, str] = {}
    for value, words in context.aliases:
        for word in words:
            start = _find(word, text)
            if start >= 0:
                hits.setdefault(value, text[start : start + len(word)])
                break
    if len(hits) != 1:
        return None
    ((value, quote),) = hits.items()
    return NormalizedValue(value=value, confidence=1.0, quote=quote)


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


def _dictionary(context: NormalizeContext) -> str:
    words = dict(context.aliases)
    return "; ".join(
        f"{value}: {', '.join(words[value])}" for value in context.values if words.get(value)
    )


def build_normalize_prompt(texts: Sequence[str], context: NormalizeContext) -> str:
    numbered = [f"{i}. {text}" for i, text in enumerate(texts, start=1)]
    dictionary = _dictionary(context)
    return "\n".join(
        [
            f"Map each free-text job description to one {context.dim} category. Answer with one",
            'JSON object and nothing else: {"answers": [{"index": 1, "value": "...",',
            '"confidence": 0.0, "quote": "..."}]} with one answer per numbered text.',
            f"Allowed values: {', '.join(context.values)}. Use another word only if none fits;",
            "it will then be reviewed by a person.",
            *([f"Approved words per value: {dictionary}."] if dictionary else []),
            "`quote` must be copied verbatim from that text. confidence is between 0 and 1;",
            "give a low value when the text is vague or names several roles.",
            "",
            "Texts:",
            *numbered,
        ]
    )


def parse_normalized(raw: str, texts: Sequence[str]) -> dict[str, NormalizedValue]:
    """Answers by text. Malformed entries are skipped (that text becomes unknown later)."""
    try:
        data = json_object(raw)
    except ValueError as error:
        raise NormalizationError(f"normalizer output is not JSON: {error}") from error
    answers = data.get("answers") if isinstance(data, dict) else None
    if not isinstance(answers, list):
        raise NormalizationError("normalizer output has no answers list")
    found: dict[str, NormalizedValue] = {}
    for item in answers:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        if not isinstance(index, int) or not 1 <= index <= len(texts):
            continue
        try:
            found[texts[index - 1]] = NormalizedValue.model_validate(
                {k: v for k, v in item.items() if k != "index"}
            )
        except ValidationError:
            continue
    return found


class ClaudeCliNormalizer:
    """Runs the Claude Code CLI in print mode. No API key; uses the user's subscription."""

    def __init__(
        self, command: Sequence[str] = ("claude", "-p"), run: Runner = run_subprocess
    ) -> None:
        self.command = tuple(command)
        self.run = run

    def normalize_batch(
        self, texts: Sequence[str], context: NormalizeContext
    ) -> dict[str, NormalizedValue]:
        """One CLI call for all texts."""
        try:
            raw = self.run(self.command, build_normalize_prompt(texts, context))
        except InterpretationError as error:
            raise NormalizationError(str(error)) from error
        return parse_normalized(raw, texts)

    def normalize(self, text: str, context: NormalizeContext) -> NormalizedValue:
        answers = self.normalize_batch([text], context)
        if text not in answers:
            raise NormalizationError("no usable answer")
        return answers[text]


NormalizerFactory = Callable[[Scenario], Normalizer]
NORMALIZERS: dict[str, NormalizerFactory] = {
    "fake": FakeNormalizer.from_scenario,
    "claude": lambda _scenario: ClaudeCliNormalizer(),
}


def _unknown(text: str) -> NormalizedValue:
    return NormalizedValue(value=UNKNOWN, confidence=0.0, quote=text)


def _checked(answer: NormalizedValue | None, text: str) -> NormalizedValue:
    """A missing answer or one whose quote is not in the text becomes unknown/0."""
    if answer is None or squash(answer.quote) not in squash(text):
        return _unknown(text)
    return answer


def resolve_texts(
    texts: Sequence[str], normalizer: Normalizer, context: NormalizeContext
) -> dict[str, NormalizedValue]:
    """One answer per distinct text: aliases first, then the normalizer (batched if it can)."""
    distinct = list(dict.fromkeys(texts))
    resolved: dict[str, NormalizedValue] = {}
    remaining: list[str] = []
    for text in distinct:
        settled = match_alias(text, context)
        if settled is None:
            remaining.append(text)
        else:
            resolved[text] = settled
    if not remaining:
        return resolved
    asked: dict[str, NormalizedValue] = {}
    batch = getattr(normalizer, "normalize_batch", None)
    if callable(batch):
        for start in range(0, len(remaining), BATCH_SIZE):
            chunk = remaining[start : start + BATCH_SIZE]
            try:
                asked.update(batch(chunk, context))
            except NormalizationError:
                continue  # this chunk's texts stay unknown
    else:
        for text in remaining:
            try:
                asked[text] = normalizer.normalize(text, context)
            except NormalizationError:
                continue
    for text in remaining:
        resolved[text] = _checked(asked.get(text), text)
    return resolved


def normalize_member(member: Member, normalizer: Normalizer, context: NormalizeContext) -> Member:
    """The member with `job_group` filled. A failed or unquotable answer becomes unknown/0."""
    if member.job is None or member.job_group is not None:
        return member
    answer = resolve_texts([member.job], normalizer, context)[member.job]
    return member.model_copy(update={"job_group": answer})


def normalize_members(scenario: ScenarioT, normalizer: Normalizer) -> ScenarioT:
    """The scenario with every member's job text normalized; unchanged without a job_group dim."""
    dimension = scenario.policy.dimensions.job_group
    if dimension is None:
        return scenario
    context = NormalizeContext(
        DIM_JOB_GROUP,
        dimension.values,
        tuple((value, tuple(words)) for value, words in dimension.aliases.items()),
    )
    pending = [
        member.job
        for registration in scenario.registrations
        for member in registration.members or ()
        if member.job is not None and member.job_group is None
    ]
    answers = resolve_texts(pending, normalizer, context) if pending else {}
    registrations: list[Registration] = []
    for registration in scenario.registrations:
        if registration.members is None:
            registrations.append(registration)
            continue
        members = tuple(
            (
                m.model_copy(update={"job_group": answers[m.job]})
                if m.job is not None and m.job_group is None
                else m
            )
            for m in registration.members
        )
        registrations.append(registration.model_copy(update={"members": members}))
    return scenario.model_copy(update={"registrations": tuple(registrations)})
