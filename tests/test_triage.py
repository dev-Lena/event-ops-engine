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

GENERIC = "generic"
GENERIC_RULES = 'supported_topic("generic").\n'
"""A supported topic with no type rule, so tests can add their own cause rules."""
ONE_CAUSE = GENERIC_RULES + (
    'cause(Q, "test_cause", E) :- '
    'about_registration(Q, R), log_event(E, R, "provider_receipt", _).\n'
)
TWO_CAUSES = ONE_CAUSE + (
    'cause(Q, "other_cause", E) :- '
    'about_registration(Q, R), log_event(E, R, "message_sent", _).\n'
)
NEEDS = GENERIC_RULES + (
    'needs(Q, "provider_receipt") :- asks_about(Q, "generic"), !cause(Q, _, _).\n'
)


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
        ({**fact("about_value", "x"), "args": ["gender", "other"]}, "unknown attribute value"),
        ({**fact("about_value", "x"), "args": ["female"]}, "expected 2 argument(s)"),
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
    scenario = scenario_with([fact("asks_about", GENERIC), fact("about_registration", "r1")])
    with Engine(load_rules() + NEEDS) as engine:
        verdict = run_triage(scenario, FakeInterpreter(), engine)
    assert verdict.kind == VerdictKind.ASK
    assert verdict.needs == ("provider_receipt",)
    assert "candidate/q1/about_registration/r1" in verdict.evidence


def test_one_cause_accepts_with_log_evidence() -> None:
    scenario = scenario_with([fact("asks_about", GENERIC), fact("about_registration", "r1")])
    with Engine(load_rules() + ONE_CAUSE) as engine:
        verdict = run_triage(scenario, FakeInterpreter(), engine)
    assert verdict.kind == VerdictKind.ACCEPT
    assert verdict.cause == "test_cause"
    assert "log/e2" in verdict.evidence and "log/e1" not in verdict.evidence


def test_two_causes_ask_a_person_to_choose() -> None:
    scenario = scenario_with([fact("asks_about", GENERIC), fact("about_registration", "r1")])
    with Engine(load_rules() + TWO_CAUSES) as engine:
        verdict = run_triage(scenario, FakeInterpreter(), engine)
    assert verdict.kind == VerdictKind.ASK
    assert verdict.causes == ("other_cause", "test_cause")
    assert {"log/e1", "log/e2"} <= set(verdict.evidence)


def test_run_triage_owns_an_engine_when_none_is_given() -> None:
    verdict = run_triage(load_triage_scenario(TRIAGE), FakeInterpreter())
    assert verdict.kind == VerdictKind.ACCEPT and verdict.cause == "external_delay"


# --- review follow-ups (PR #38) ----------------------------------------------------------


def test_shared_engine_is_left_clean_between_questions() -> None:
    scenario = load_triage_scenario(TRIAGE)
    with Engine() as engine:
        first = run_triage(scenario, FakeInterpreter(), engine)
        assert engine.snapshot("question") == [] and engine.snapshot("asks_about") == []
        second = run_triage(scenario, FakeInterpreter(), engine)
    assert first.kind == second.kind == VerdictKind.ACCEPT
    assert first.evidence == second.evidence


def test_empty_interpretation_asks_instead_of_abstaining() -> None:
    verdict = run_triage(scenario_with([]), FakeInterpreter())
    assert verdict.kind == VerdictKind.ASK
    assert "찾지 못했습니다" in verdict.message


def test_duplicate_candidates_count_once() -> None:
    scenario = scenario_with(
        [
            fact("asks_about", GENERIC),
            fact("about_registration", "r1"),
            fact("about_registration", "r1", quote="r1"),
        ]
    )
    with Engine(load_rules() + ONE_CAUSE) as engine:
        verdict = run_triage(scenario, FakeInterpreter(), engine)
    assert verdict.evidence.count("candidate/q1/about_registration/r1") == 1


def test_quote_matches_across_whitespace_differences() -> None:
    scenario = scenario_with([fact("about_registration", "r1", quote="r1  신청자")])
    assert scenario.question.canned is not None
    assert validate(scenario.question.canned, scenario) == []


def test_about_event_and_about_session_reach_the_rules() -> None:
    rules = GENERIC_RULES + (
        'cause(Q, "by_event", E) :- about_event(Q, E), log_event(E, _, "provider_receipt", _).\n'
        'cause(Q, "by_session", "e1") :- about_session(Q, S), registration(_, S).\n'
    )
    event_q = scenario_with([fact("asks_about", GENERIC), fact("about_event", "e2")])
    session_q = scenario_with([fact("asks_about", GENERIC), fact("about_session", "s1")])
    with Engine(load_rules() + rules) as engine:
        by_event = run_triage(event_q, FakeInterpreter(), engine)
        by_session = run_triage(session_q, FakeInterpreter(), engine)
    assert (by_event.cause, by_session.cause) == ("by_event", "by_session")
    assert "log/e2" in by_event.evidence


def test_log_events_are_hashable_despite_the_attrs_dict() -> None:
    scenario = load_triage_scenario(TRIAGE)
    assert len(set(scenario.log)) == 2


# --- candidate confidence (#59) ------------------------------------------------------------


def with_confidence(item: dict[str, object], confidence: float) -> dict[str, object]:
    return {**item, "confidence": confidence}


def test_low_confidence_candidates_never_reach_the_rules() -> None:
    scenario = scenario_with(
        [fact("asks_about", GENERIC), with_confidence(fact("about_registration", "r1"), 0.59)]
    )
    with Engine(load_rules() + ONE_CAUSE) as engine:
        verdict = run_triage(scenario, FakeInterpreter(), engine)
    assert verdict.kind == VerdictKind.ASK  # without the subject, no cause
    assert "candidate/q1/about_registration/r1" not in verdict.evidence
    assert "확신이 낮아" in verdict.message and "about_registration r1 (0.59)" in verdict.message
    assert any("dropped 1 low-confidence" in step for step in verdict.trace)


def test_candidate_at_the_threshold_is_used() -> None:
    scenario = scenario_with(
        [fact("asks_about", GENERIC), with_confidence(fact("about_registration", "r1"), 0.6)]
    )
    with Engine(load_rules() + ONE_CAUSE) as engine:
        verdict = run_triage(scenario, FakeInterpreter(), engine)
    assert verdict.kind == VerdictKind.ACCEPT and "확신이 낮아" not in verdict.message


def test_invented_facts_are_rejected_even_when_unsure() -> None:
    scenario = scenario_with([with_confidence(fact("about_registration", "r9"), 0.1)])
    assert run(scenario) == VerdictKind.REJECT


def test_threshold_comes_from_the_policy() -> None:
    base = scenario_with(
        [fact("asks_about", GENERIC), with_confidence(fact("about_registration", "r1"), 0.5)]
    )
    triage_policy = base.policy.triage.model_copy(update={"min_candidate_confidence": 0.4})
    lenient = base.model_copy(
        update={"policy": base.policy.model_copy(update={"triage": triage_policy})}
    )
    with Engine(load_rules() + ONE_CAUSE) as engine:
        assert run_triage(lenient, FakeInterpreter(), engine).kind == VerdictKind.ACCEPT
