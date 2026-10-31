"""Type rules: 1 user input (account length, #15) and 2 external delay (#16), end to end."""

from pathlib import Path

import pytest

from event_ops_engine.cli import VERDICT_LABELS
from event_ops_engine.decision import VerdictKind
from event_ops_engine.harness import differences, run_triage
from event_ops_engine.interpreter import FakeInterpreter
from event_ops_engine.loader import load_triage_scenario
from event_ops_engine.model import LogEvent, TriageScenario
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
