"""Type rules: 1 user input (account length, #15) and 2 external delay (#16), end to end."""

from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from event_ops_engine.cli import VERDICT_LABELS
from event_ops_engine.decision import VerdictKind
from event_ops_engine.harness import differences, run_triage
from event_ops_engine.interpreter import FakeInterpreter
from event_ops_engine.loader import load_triage_scenario
from event_ops_engine.model import EventPolicy, LogEvent, TriagePolicy, TriageScenario
from tests.conftest import SCENARIOS

TRIAGE = SCENARIOS / "triage"
FILES = sorted(TRIAGE.glob("*.yaml"))


def verdict_for(scenario: TriageScenario) -> tuple[VerdictKind, str | None, tuple[str, ...]]:
    verdict = run_triage(scenario, FakeInterpreter())
    return verdict.kind, verdict.cause, verdict.needs


def with_log(path: Path, log: list[LogEvent]) -> TriageScenario:
    return load_triage_scenario(path).model_copy(update={"log": tuple(log)})


@pytest.mark.parametrize("path", FILES, ids=[p.stem for p in FILES])
def test_every_synthetic_question_gets_its_expected_verdict(path: Path) -> None:
    scenario = load_triage_scenario(path)
    assert scenario.expected is not None, "triage scenarios state the expected verdict"
    assert differences(run_triage(scenario, FakeInterpreter()), scenario.expected) == []


# --- type 1 ---------------------------------------------------------------------------


def test_account_length_mismatch_is_user_input_with_both_events_as_evidence() -> None:
    verdict = run_triage(load_triage_scenario(TRIAGE / "account-length.yaml"), FakeInterpreter())
    assert (verdict.kind, verdict.cause) == (VerdictKind.ACCEPT, "user_input")
    assert {"log/e1", "log/e2"} <= set(verdict.evidence)


def test_matching_account_length_derives_no_cause() -> None:
    scenario = load_triage_scenario(TRIAGE / "account-length.yaml")
    issued, entered = scenario.log
    same = entered.model_copy(update={"attrs": {**entered.attrs, "digits": issued.attrs["digits"]}})
    kind, cause, needs = verdict_for(scenario.model_copy(update={"log": (issued, same)}))
    assert (kind, cause, needs) == (VerdictKind.ASK, None, ())


def test_no_issued_account_asks_for_it() -> None:
    scenario = with_log(TRIAGE / "account-missing-entry.yaml", [])
    assert verdict_for(scenario) == (VerdictKind.ASK, None, ("account_issued",))


# --- type 2 ---------------------------------------------------------------------------


def test_receipt_before_the_timeout_does_not_explain_it() -> None:
    scenario = load_triage_scenario(TRIAGE / "delivery-timeout.yaml")
    sent, receipt = scenario.log
    early = receipt.model_copy(update={"at": sent.at.replace(hour=9)})
    assert verdict_for(scenario.model_copy(update={"log": (sent, early)}))[0] == VerdictKind.ASK


def test_failed_receipt_is_not_a_delay() -> None:
    scenario = load_triage_scenario(TRIAGE / "delivery-timeout.yaml")
    sent, receipt = scenario.log
    failed = receipt.model_copy(update={"attrs": {**receipt.attrs, "result": "failed"}})
    kind, cause, needs = verdict_for(scenario.model_copy(update={"log": (sent, failed)}))
    assert (kind, cause, needs) == (VerdictKind.ASK, None, ())


def test_question_may_name_the_registration_through_a_log_event() -> None:
    # delivery-no-receipt points at the send event (about_event), not the registration
    scenario = load_triage_scenario(TRIAGE / "delivery-no-receipt.yaml")
    receipt = scenario.log[0].model_copy(
        update={"id": "e2", "kind": "provider_receipt", "attrs": {"result": "delivered"}}
    )
    verdict = run_triage(
        scenario.model_copy(update={"log": (*scenario.log, receipt)}), FakeInterpreter()
    )
    assert (verdict.kind, verdict.cause) == (VerdictKind.ACCEPT, "external_delay")
    assert "candidate/q1/about_event/e1" in verdict.evidence


def test_another_registrations_receipt_does_not_count() -> None:
    scenario = load_triage_scenario(TRIAGE / "delivery-no-receipt.yaml")
    other = scenario.registrations[0].model_copy(update={"id": "r2"})
    receipt = scenario.log[0].model_copy(
        update={
            "id": "e2",
            "kind": "provider_receipt",
            "registration": "r2",
            "attrs": {"result": "delivered"},
        }
    )
    scenario = scenario.model_copy(
        update={"registrations": (*scenario.registrations, other), "log": (*scenario.log, receipt)}
    )
    assert verdict_for(scenario) == (VerdictKind.ASK, None, ("provider_receipt",))


# --- several events per registration (PR #39 review) ---------------------------------------


def test_reissued_account_is_compared_with_the_latest_issue_only() -> None:
    scenario = load_triage_scenario(TRIAGE / "account-length.yaml")
    issued, entered = scenario.log  # issued 14 digits, entered 13
    reissued = issued.model_copy(
        update={"id": "e3", "at": issued.at.replace(minute=20), "attrs": {"digits": 13}}
    )
    kind, cause, needs = verdict_for(
        scenario.model_copy(update={"log": (issued, reissued, entered)})
    )
    assert (kind, cause, needs) == (VerdictKind.ASK, None, ())  # the latest issue matches


def test_corrected_entry_supersedes_the_wrong_one() -> None:
    scenario = load_triage_scenario(TRIAGE / "account-length.yaml")
    issued, entered = scenario.log
    corrected = entered.model_copy(
        update={"id": "e3", "at": entered.at.replace(hour=10), "attrs": {"digits": 14}}
    )
    assert verdict_for(scenario.model_copy(update={"log": (issued, entered, corrected)}))[0] == (
        VerdictKind.ASK
    )


def test_receipt_after_a_resend_does_not_explain_the_first_timeout() -> None:
    scenario = load_triage_scenario(TRIAGE / "delivery-timeout.yaml")
    sent, receipt = scenario.log
    resend = sent.model_copy(
        update={"id": "e3", "at": sent.at.replace(minute=1), "attrs": {"result": "ok"}}
    )
    verdict = run_triage(
        scenario.model_copy(update={"log": (sent, resend, receipt)}), FakeInterpreter()
    )
    assert verdict.kind == VerdictKind.ASK and verdict.needs == ()


def test_accept_never_carries_needs_from_another_event() -> None:
    scenario = load_triage_scenario(TRIAGE / "delivery-timeout.yaml")
    sent, receipt = scenario.log
    earlier = sent.model_copy(update={"id": "e0", "at": sent.at.replace(day=31, month=10)})
    verdict = run_triage(
        scenario.model_copy(update={"log": (earlier, sent, receipt)}), FakeInterpreter()
    )
    assert (verdict.kind, verdict.cause, verdict.needs) == (
        VerdictKind.ACCEPT,
        "external_delay",
        (),
    )


def test_every_verdict_kind_has_a_label() -> None:
    assert set(VERDICT_LABELS) == set(VerdictKind)


# --- type 3 ---------------------------------------------------------------------------

DUPLICATE = TRIAGE / "duplicate-reregistration.yaml"


def test_duplicate_in_the_same_session_is_policy_normal_with_both_submissions() -> None:
    verdict = run_triage(load_triage_scenario(DUPLICATE), FakeInterpreter())
    assert (verdict.kind, verdict.cause) == (VerdictKind.ACCEPT, "policy_normal")
    assert {"log/e1", "log/e2"} <= set(verdict.evidence)


def test_same_participant_in_another_session_is_not_a_duplicate() -> None:
    scenario = load_triage_scenario(DUPLICATE)
    other_session = scenario.sessions[0].model_copy(update={"id": "s2"})
    moved = scenario.registrations[0].model_copy(update={"session": "s2"})
    scenario = scenario.model_copy(
        update={
            "sessions": (*scenario.sessions, other_session),
            "registrations": (moved, scenario.registrations[1]),
        }
    )
    assert verdict_for(scenario) == (VerdictKind.ASK, None, ())


def test_different_participant_keys_derive_nothing() -> None:
    scenario = load_triage_scenario(DUPLICATE)
    first, second = scenario.log
    other = first.model_copy(update={"attrs": {"participant": "p2"}})
    assert verdict_for(scenario.model_copy(update={"log": (other, second)})) == (
        VerdictKind.ASK,
        None,
        (),
    )


def test_missing_submission_event_asks_for_it() -> None:
    scenario = load_triage_scenario(DUPLICATE)
    scenario = scenario.model_copy(update={"log": (scenario.log[0],)})  # r2 has none
    assert verdict_for(scenario) == (VerdictKind.ASK, None, ("registration_submitted",))


# --- type 4 ---------------------------------------------------------------------------

DEADLINE = TRIAGE / "deadline-expired.yaml"


def attempt_at(scenario: TriageScenario, offset_seconds: int) -> TriageScenario:
    due, attempt = scenario.log
    moved = attempt.model_copy(update={"at": due.at + timedelta(seconds=offset_seconds)})
    return scenario.model_copy(update={"log": (due, moved)})


@pytest.mark.parametrize(
    "offset_seconds, expected",
    [(0, VerdictKind.ASK), (600, VerdictKind.ASK), (601, VerdictKind.ACCEPT)],
    ids=["at_due", "grace_end", "past_grace"],
)
def test_grace_boundary(offset_seconds: int, expected: VerdictKind) -> None:
    scenario = attempt_at(load_triage_scenario(DEADLINE), offset_seconds)
    kind, cause, _ = verdict_for(scenario)
    assert kind == expected and cause == ("expired" if expected == VerdictKind.ACCEPT else None)


def test_grace_comes_from_the_policy() -> None:
    scenario = attempt_at(load_triage_scenario(DEADLINE), 1)
    strict = scenario.policy.model_copy(update={"triage": TriagePolicy(grace_minutes=0)})
    assert verdict_for(scenario.model_copy(update={"policy": strict}))[1] == "expired"


def test_extended_deadline_supersedes_the_old_one() -> None:
    scenario = load_triage_scenario(DEADLINE)
    due, attempt = scenario.log
    extended = due.model_copy(update={"id": "e3", "at": attempt.at + timedelta(hours=1)})
    assert verdict_for(scenario.model_copy(update={"log": (due, extended, attempt)})) == (
        VerdictKind.ASK,
        None,
        (),
    )


@pytest.mark.parametrize(
    "keep, needed",
    [(1, "payment_due"), (0, "payment_attempt")],
    ids=["no_due", "no_attempt"],
)
def test_missing_deadline_events_are_named(keep: int, needed: str) -> None:
    scenario = load_triage_scenario(DEADLINE)
    scenario = scenario.model_copy(update={"log": (scenario.log[keep],)})
    assert verdict_for(scenario) == (VerdictKind.ASK, None, (needed,))


def test_triage_policy_defaults_and_rejects_negative_grace() -> None:
    policy = load_triage_scenario(DEADLINE).policy
    assert (
        EventPolicy.model_validate(
            {**policy.model_dump(by_alias=True), "triage": {}}
        ).triage.grace_minutes
        == TriagePolicy().grace_minutes
    )
    with pytest.raises(ValidationError):
        TriagePolicy(grace_minutes=-1)


# --- expected verdict --------------------------------------------------------------------


def test_differences_name_kind_cause_and_needs() -> None:
    scenario = load_triage_scenario(TRIAGE / "account-length.yaml")
    verdict = run_triage(scenario, FakeInterpreter())
    assert scenario.expected is not None
    wrong = scenario.expected.model_copy(update={"kind": VerdictKind.ASK, "needs": ("x",)})
    found = differences(verdict, wrong)
    assert len(found) == 2 and found[0].startswith("kind:") and found[1].startswith("needs:")
    loose = scenario.expected.model_copy(update={"cause": None, "needs": None})
    assert differences(verdict, loose) == []
