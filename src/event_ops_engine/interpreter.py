"""Layer: services. Turns an operator question into candidate facts (INTERPRET stage).

Two implementations: `ClaudeCliInterpreter` runs `claude -p` (subscription, no API cost) and
`FakeInterpreter` returns the scenario's canned answer so tests are offline and deterministic.
Either way the output is only a proposal: `harness.py` validates it and the rules decide.
See docs/design.md 13.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import ValidationError

from .facts import CANDIDATE_RELATIONS, TOPICS, dimension_values
from .model import Interpretation, Question, TriageScenario


class InterpretationError(Exception):
    """The interpreter produced nothing usable. The harness turns this into `reject`."""


@dataclass(frozen=True)
class InterpretContext:
    """Everything the interpreter may refer to. Ids outside these sets are rejected later."""

    registrations: tuple[str, ...]
    sessions: tuple[str, ...]
    log_ids: tuple[str, ...]
    values: tuple[tuple[str, str], ...] = ()
    """(dim, value) pairs the policy defines, e.g. ("gender", "female")."""
    topics: tuple[str, ...] = TOPICS

    @classmethod
    def from_scenario(cls, scenario: TriageScenario) -> InterpretContext:
        return cls(
            registrations=tuple(r.id for r in scenario.registrations),
            sessions=tuple(s.id for s in scenario.sessions),
            log_ids=tuple(e.id for e in scenario.log),
            values=dimension_values(scenario.policy),
        )


class Interpreter(Protocol):
    def interpret(self, question: Question, context: InterpretContext) -> Interpretation: ...


class FakeInterpreter:
    """Returns the question's `canned` interpretation. Tests and synthetic scenarios only."""

    def interpret(self, question: Question, context: InterpretContext) -> Interpretation:
        if question.canned is None:
            raise InterpretationError(f"question {question.id}: no canned interpretation")
        return question.canned


Runner = Callable[[Sequence[str], str], str]
"""(command, stdin) -> stdout."""


def run_subprocess(command: Sequence[str], stdin: str, timeout: float = 120.0) -> str:
    completed = subprocess.run(
        list(command), input=stdin, capture_output=True, text=True, timeout=timeout, check=False
    )
    if completed.returncode != 0:
        detail = (completed.stderr.strip() or completed.stdout.strip())[-300:]
        raise InterpretationError(f"{command[0]} exited {completed.returncode}: {detail}")
    return completed.stdout


def build_prompt(question: Question, context: InterpretContext) -> str:
    relations = ", ".join(
        f"{name}(q, {', '.join(kinds)})" for name, kinds in CANDIDATE_RELATIONS.items()
    )
    values = ", ".join(f"{dim}={value}" for dim, value in context.values) or "(none)"
    return "\n".join(
        [
            "You extract candidate facts from an event-operations inquiry. Propose facts only;",
            "you never decide the cause. Answer with one JSON object and nothing else:",
            '{"facts": [{"relation": "...", "args": ["..."], "provenance": {"source": "question",',
            '"quote": "..."}, "confidence": 0.0}], "note": ""}',
            f"Allowed relations and their arguments after q: {relations}.",
            f"Topics: {', '.join(context.topics)}. Use another topic word if none fits.",
            f"Known registration ids: {', '.join(context.registrations) or '(none)'}.",
            f"Known session ids: {', '.join(context.sessions) or '(none)'}.",
            f"Known log event ids: {', '.join(context.log_ids) or '(none)'}.",
            f"Known attribute values (dim=value, two arguments for about_value): {values}.",
            "Rules: `quote` must be copied verbatim from the question. Never invent an id that is",
            "not listed. Omit a fact rather than guess. confidence is between 0 and 1.",
            "",
            "Question:",
            question.text,
        ]
    )


def json_object(raw: str) -> Any:
    """The outermost JSON object in a model's output, or ValueError."""
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in the output")
    try:
        return json.loads(raw[start : end + 1])
    except json.JSONDecodeError as error:
        raise ValueError(f"malformed JSON: {error}") from error


def parse_interpretation(raw: str) -> Interpretation:
    """Accept the first JSON object in the output; anything else is an error."""
    try:
        return Interpretation.model_validate(json_object(raw))
    except (ValueError, ValidationError) as error:
        raise InterpretationError(
            f"interpreter output does not match the schema: {error}"
        ) from error


PREFLIGHT_PROMPT = "Reply with exactly: ok"


def preflight(
    command: Sequence[str] = ("claude", "-p"), run: Runner = run_subprocess
) -> str | None:
    """None when the CLI answers, else why it cannot be used (e.g. not logged in).

    "Installed" is not "logged in": a logged-out CLI would turn every question into a reject,
    so the CLI checks once before it starts.
    """
    try:
        run(command, PREFLIGHT_PROMPT)
    except InterpretationError as error:
        return str(error)
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"{command[0]}: {error}"
    return None


class ClaudeCliInterpreter:
    """Runs the Claude Code CLI in print mode. No API key; uses the user's subscription."""

    def __init__(
        self, command: Sequence[str] = ("claude", "-p"), run: Runner = run_subprocess
    ) -> None:
        self.command = tuple(command)
        self.run = run

    def interpret(self, question: Question, context: InterpretContext) -> Interpretation:
        return parse_interpretation(self.run(self.command, build_prompt(question, context)))
