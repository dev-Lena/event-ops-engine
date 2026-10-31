"""Module ① contract: candidate-fact validation, the five stages and the four verdicts."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from event_ops_engine.decision import VerdictKind
from event_ops_engine.engine import Engine, load_rules
from event_ops_engine.harness import run_triage, validate
from event_ops_engine.interpreter import FakeInterpreter, InterpretContext
from event_ops_engine.loader import load_triage_scenario
from event_ops_engine.model import CandidateFact, Interpretation, Question, TriageScenario
from tests.conftest import SCENARIOS

TRIAGE = SCENARIOS / "triage" / "delivery-timeout.yaml"

ONE_CAUSE = (
    'cause(Q, "test_cause", E) :- '
    'about_registration(Q, R), log_event(E, R, "provider_receipt", _).\n'
)
TWO_CAUSES = ONE_CAUSE + (
    'cause(Q, "other_cause", E) :- '
    'about_registration(Q, R), log_event(E, R, "message_sent", _).\n'
)
NEEDS = 'needs(Q, "provider_receipt") :- asks_about(Q, "delivery"), !cause(Q, _, _).\n'


def scenario_with(facts: list[dict[str, object]], text: str | None = None) -> TriageScenario:
    base = load_triage_scenario(TRIAGE)
    question = Question(
        id="q1",
        text=text or base.question.text,
        canned=Interpretation.model_validate({"facts": facts}),
    )
    return base.model_copy(update={"question": question})


def fact(relation: str, arg: str, quote: str = "r1 신청자") -> dict[str, object]:
    return {
        "relation": relation,
        "args": [arg],
        "provenance": {"source": "question", "quote": quote},
        "confidence": 0.9,
    }


def run(scenario: TriageScenario, extra_rules: str = "") -> VerdictKind:
    with Engine(load_rules() + extra_rules) as engine:
        verdict = run_triage(scenario, FakeInterpreter(), engine)
    assert verdict.evidence  # every verdict carries evidence
    assert verdict.trace[0].startswith("ADAPT") and verdict.trace[-1].startswith("ACT")
    return verdict.kind


# --- models ---------------------------------------------------------------------------


def test_candidate_fact_needs_provenance_and_bounded_confidence() -> None:
    with pytest.raises(ValidationError):
        CandidateFact.model_validate(
            {"relation": "asks_about", "args": ["payment"], "confidence": 0.5}
        )
    with pytest.raises(ValidationError):
        CandidateFact.model_validate(
            {
                "relation": "asks_about",
                "args": ["payment"],
                "provenance": {"quote": "x"},
                "confidence": 1.5,
            }
        )


def test_log_events_must_reference_known_registrations() -> None:
    base = load_triage_scenario(TRIAGE)
    with pytest.raises(ValidationError, match="unknown registration"):
        TriageScenario.model_validate(
            {
                **base.model_dump(by_alias=True),
                "log": [
                    {
                        "id": "e9",
                        "at": datetime(2026, 11, 1, tzinfo=timezone.utc),
                        "kind": "x",
                        "registration": "nope",
                    }
                ],
            }
        )


def test_example_scenario_loads_with_log_and_canned_answer() -> None:
    scenario = load_triage_scenario(TRIAGE)
    assert [e.kind for e in scenario.log] == ["message_sent", "provider_receipt"]
    assert scenario.question.canned is not None
    assert InterpretContext.from_scenario(scenario).log_ids == ("e1", "e2")


# --- validation (reject) ---------------------------------------------------------------


@pytest.mark.parametrize(
    "bad, problem",
    [
        (fact("invented_relation", "r1"), "unknown relation"),
        (fact("about_registration", "r9"), "unknown registration id"),
        (fact("about_event", "e9"), "unknown log id"),
        (fact("about_session", "s1", quote="없는 문장"), "quote not found"),
    ],
)
def test_invented_facts_are_rejected(bad: dict[str, object], problem: str) -> None:
    scenario = scenario_with([bad])
    assert scenario.question.canned is not None
    assert any(problem in p for p in validate(scenario.question.canned, scenario))
    assert run(scenario) == VerdictKind.REJECT


def test_interpreter_failure_is_a_reject_not_a_crash() -> None:
    base = load_triage_scenario(TRIAGE)
    scenario = base.model_copy(update={"question": Question(id="q1", text="?")})  # no canned answer
    assert run(scenario) == VerdictKind.REJECT


# --- decision contract -----------------------------------------------------------------


def test_unsupported_topic_abstains() -> None:
    assert run(scenario_with([fact("asks_about", "weather")])) == VerdictKind.ABSTAIN


def test_no_cause_in_scope_asks_and_names_what_is_needed() -> None:
    scenario = scenario_with([fact("asks_about", "delivery"), fact("about_registration", "r1")])
    with Engine(load_rules() + NEEDS) as engine:
        verdict = run_triage(scenario, FakeInterpreter(), engine)
    assert verdict.kind == VerdictKind.ASK
    assert verdict.needs == ("provider_receipt",)
    assert "candidate/q1/about_registration/r1" in verdict.evidence


def test_one_cause_accepts_with_log_evidence() -> None:
    scenario = scenario_with([fact("asks_about", "delivery"), fact("about_registration", "r1")])
    with Engine(load_rules() + ONE_CAUSE) as engine:
        verdict = run_triage(scenario, FakeInterpreter(), engine)
    assert verdict.kind == VerdictKind.ACCEPT
    assert verdict.cause == "test_cause"
    assert "log/e2" in verdict.evidence and "log/e1" not in verdict.evidence


def test_two_causes_ask_a_person_to_choose() -> None:
    scenario = scenario_with([fact("asks_about", "delivery"), fact("about_registration", "r1")])
    with Engine(load_rules() + TWO_CAUSES) as engine:
        verdict = run_triage(scenario, FakeInterpreter(), engine)
    assert verdict.kind == VerdictKind.ASK
    assert verdict.causes == ("other_cause", "test_cause")
    assert {"log/e1", "log/e2"} <= set(verdict.evidence)


def test_run_triage_owns_an_engine_when_none_is_given() -> None:
    verdict = run_triage(load_triage_scenario(TRIAGE), FakeInterpreter())
    assert verdict.kind == VerdictKind.ASK  # no type rules yet (#16)
