"""Interpreters: the fake returns canned answers; the CLI one parses JSON and never calls out."""

from collections.abc import Sequence

import pytest

from event_ops_engine.interpreter import (
    ClaudeCliInterpreter,
    FakeInterpreter,
    InterpretationError,
    InterpretContext,
    build_prompt,
    parse_interpretation,
)
from event_ops_engine.model import Interpretation, Question

CONTEXT = InterpretContext(
    registrations=("r1",),
    sessions=("s1",),
    log_ids=("e1", "e2"),
    values=(("gender", "female"),),
)
CANNED = Interpretation.model_validate(
    {
        "facts": [
            {
                "relation": "asks_about",
                "args": ["delivery"],
                "provenance": {"quote": "문자를"},
                "confidence": 0.9,
            }
        ]
    }
)


def test_fake_returns_the_canned_answer_or_fails_loudly() -> None:
    question = Question(id="q1", text="문자를 못 받았대요", canned=CANNED)
    assert FakeInterpreter().interpret(question, CONTEXT) is CANNED
    with pytest.raises(InterpretationError):
        FakeInterpreter().interpret(Question(id="q2", text="?"), CONTEXT)


def test_cli_interpreter_parses_json_wrapped_in_prose() -> None:
    seen: dict[str, object] = {}

    def fake_run(command: Sequence[str], stdin: str) -> str:
        seen["command"], seen["stdin"] = tuple(command), stdin
        return (
            'Sure. {"facts": [{"relation": "about_registration", "args": ["r1"], '
            '"provenance": {"source": "question", "quote": "r1"}, "confidence": 0.8}], '
            '"note": "ok"} Done.'
        )

    interpreter = ClaudeCliInterpreter(command=("claude", "-p"), run=fake_run)
    result = interpreter.interpret(Question(id="q1", text="r1 왜 안 되나요"), CONTEXT)
    assert result.facts[0].relation == "about_registration"
    assert result.note == "ok"
    assert seen["command"] == ("claude", "-p")
    prompt = str(seen["stdin"])
    assert "r1 왜 안 되나요" in prompt and "Known log event ids: e1, e2" in prompt


@pytest.mark.parametrize(
    "raw",
    ["no json here", '{"facts": "not a list"}', '{"facts": [{"relation": "x"}]}', "{broken"],
)
def test_unusable_cli_output_is_an_interpretation_error(raw: str) -> None:
    with pytest.raises(InterpretationError):
        parse_interpretation(raw)


def test_prompt_lists_allowed_relations_and_forbids_invented_ids() -> None:
    prompt = build_prompt(Question(id="q", text="hi"), CONTEXT)
    assert "asks_about(q, topic)" in prompt and "about_event(q, log)" in prompt
    assert "about_value(q, dim, value)" in prompt and "gender=female" in prompt
    assert "Never invent an id" in prompt


def test_preflight_reports_why_the_cli_cannot_be_used() -> None:
    import subprocess

    from event_ops_engine.interpreter import preflight

    def logged_out(command: Sequence[str], stdin: str) -> str:
        raise InterpretationError("claude exited 1: Failed to authenticate")

    def missing(command: Sequence[str], stdin: str) -> str:
        raise FileNotFoundError("claude")

    def slow(command: Sequence[str], stdin: str) -> str:
        raise subprocess.TimeoutExpired(list(command), 120)

    assert preflight(run=lambda command, stdin: "ok") is None
    assert "Failed to authenticate" in (preflight(run=logged_out) or "")
    assert (preflight(run=missing) or "").startswith("claude:")
    assert (preflight(run=slow) or "").startswith("claude:")
