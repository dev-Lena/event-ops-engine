"""An extra registration or topic, or a missing record, must not turn `ask` into `accept` (#101).

Synthetic repro scenarios from the 2026-11-10 review. Two registrations whose logs give
different answers:

- r1, the one the question is about: the account digits match and it is still pending with
  no payment lookup, so the right verdict is `ask` for `payment_lookup`. r1 also has a
  timed-out message with a delivered receipt (topic `delivery` would give `external_delay`).
- r2, not in the question: the account digits differ (`user_input`).
"""

from pathlib import Path

import pytest

from event_ops_engine.decision import Verdict, VerdictKind
from event_ops_engine.harness import MIN_QUOTE_CHARS, names_id, run_triage, validate
from event_ops_engine.interpreter import FakeInterpreter, InterpretContext, build_prompt
from event_ops_engine.loader import load_triage_scenario
from event_ops_engine.model import Interpretation, Question, TriageScenario
from tests.conftest import POLICY

TEXT = "r1 신청자가 입금하려는데 계좌가 없다고 나온대요. 계좌 발급이 잘못됐나요?"
TWO_REGISTRATIONS = f"""
policy: {POLICY}
now: 2026-11-07T10:00:00+09:00
sessions:
  - {{ id: s1, date: 2026-11-21 }}
registrations:
  - {{ id: r1, session: s1, members: [{{ gender: female, birth_year: 1998 }}],
      status_events: [{{ at: 2026-11-02T09:00:00+09:00, status: pending_payment }}] }}
  - {{ id: r2, session: s1, members: [{{ gender: male, birth_year: 1990 }}],
      status_events: [{{ at: 2026-11-02T09:00:00+09:00, status: pending_payment }}] }}
log:
  - {{ id: e1, at: 2026-11-02T09:00:01+09:00, kind: account_issued, registration: r1,
      attrs: {{ digits: 14 }} }}
  - {{ id: e2, at: 2026-11-02T09:40:00+09:00, kind: account_entered, registration: r1,
      attrs: {{ digits: 14 }} }}
  - {{ id: e3, at: 2026-11-02T09:00:05+09:00, kind: message_sent, registration: r1,
      attrs: {{ result: timeout }} }}
  - {{ id: e4, at: 2026-11-02T09:02:00+09:00, kind: provider_receipt, registration: r1,
      attrs: {{ result: delivered }} }}
  - {{ id: e5, at: 2026-11-02T09:00:01+09:00, kind: account_issued, registration: r2,
      attrs: {{ digits: 14 }} }}
  - {{ id: e6, at: 2026-11-02T09:40:00+09:00, kind: account_entered, registration: r2,
      attrs: {{ digits: 13 }} }}
question:
  id: q1
  text: "{TEXT}"
"""
ONE_REGISTRATION = f"""
policy: {POLICY}
now: 2026-11-07T10:00:00+09:00
sessions:
  - {{ id: s1, date: 2026-11-21 }}
registrations:
  - {{ id: r1, session: s1, members: [{{ gender: female, birth_year: 1995 }}],
      status_events: [STATUS] }}
log: [LOG]
question:
  id: q1
  text: "r1 신청자가 입금하려는데 은행에서 거절됐대요. 왜 그런가요?"
"""
PENDING = "{ at: 2026-11-01T10:00:00+09:00, status: pending_payment }"
CONFIRMED = PENDING + ", { at: 2026-11-01T12:00:00+09:00, status: confirmed }"
PAYMENT = ("asks_about", "payment", "입금하려는데")
R1 = ("about_registration", "r1", "r1 신청자")


def fact(relation: str, arg: str, quote: str) -> dict[str, object]:
    return {
        "relation": relation,
        "args": [arg],
        "provenance": {"source": "question", "quote": quote},
        "confidence": 0.9,
    }


def scenario(tmp_path: Path, body: str, *facts: tuple[str, str, str]) -> TriageScenario:
    path = tmp_path / "scenario.yaml"
    path.write_text(body, encoding="utf-8")
    loaded = load_triage_scenario(path)
    canned = Interpretation.model_validate({"facts": [fact(*f) for f in facts]})
    question = Question(id="q1", text=loaded.question.text, canned=canned)
    return loaded.model_copy(update={"question": question})


def two(tmp_path: Path, *facts: tuple[str, str, str]) -> Verdict:
    return run_triage(scenario(tmp_path, TWO_REGISTRATIONS, *facts), FakeInterpreter())


def one(tmp_path: Path, status: str, log: str, *facts: tuple[str, str, str]) -> Verdict:
    body = ONE_REGISTRATION.replace("STATUS", status).replace("LOG", log)
    return run_triage(scenario(tmp_path, body, *facts), FakeInterpreter())


def outcome(verdict: Verdict) -> tuple[VerdictKind, str | None, tuple[str, ...]]:
    return verdict.kind, verdict.cause, verdict.needs


# --- (d) the quote must be real and name its registration ---------------------------------


def test_control_right_interpretation_asks_for_the_payment_lookup(tmp_path: Path) -> None:
    assert outcome(two(tmp_path, PAYMENT, R1)) == (VerdictKind.ASK, None, ("payment_lookup",))


def test_quote_naming_r1_cannot_justify_r2(tmp_path: Path) -> None:
    """Was `accept · user_input`: r2 was picked with the quote "r1 신청자"."""
    verdict = two(tmp_path, PAYMENT, ("about_registration", "r2", "r1 신청자"))
    assert verdict.kind == VerdictKind.REJECT
    assert "quote does not name registration r2" in verdict.message


@pytest.mark.parametrize("quote", [" ", "\n\t", "가"], ids=["space", "blank", "one"])
def test_blank_or_one_character_quote_is_rejected(tmp_path: Path, quote: str) -> None:
    """Was `accept · user_input`: a blank quote is "found" in every question.

    An empty string never gets this far; the model already requires one character.
    """
    verdict = two(tmp_path, PAYMENT, ("about_registration", "r2", quote))
    assert verdict.kind == VerdictKind.REJECT
    assert f"shorter than {MIN_QUOTE_CHARS} characters" in verdict.message


def test_registration_id_must_be_a_whole_token() -> None:
    assert names_id("r1 신청자", "r1") and names_id("신청 R1번", "r1") and names_id("(r1)", "r1")
    assert not names_id("r12 신청자", "r1") and not names_id("r1-b 신청자", "r1")
    assert not names_id("신청자가", "r2")


def test_other_relations_are_not_tied_to_an_id(tmp_path: Path) -> None:
    """A log event is named by what happened ("timeout"), not by its id."""
    base = scenario(tmp_path, TWO_REGISTRATIONS, ("about_event", "e3", "계좌가 없다고"))
    assert base.question.canned is not None
    assert validate(base.question.canned, base) == []


def test_prompt_tells_the_interpreter_about_the_quote_rules() -> None:
    context = InterpretContext(registrations=("r1", "r2"), sessions=("s1",), log_ids=())
    prompt = build_prompt(Question(id="q1", text=TEXT), context)
    assert "at least two characters" in prompt
    assert "its quote must contain that id" in prompt


# --- (b) a cause for an extra registration or topic keeps the question's own needs ---------


def test_extra_topic_keeps_the_needs_of_the_asked_topic(tmp_path: Path) -> None:
    """Was `accept · external_delay`: the delivery cause wiped the payment topic's needs."""
    verdict = two(tmp_path, PAYMENT, ("asks_about", "delivery", "나온대요"), R1)
    assert outcome(verdict) == (VerdictKind.ASK, None, ("payment_lookup",))
    assert verdict.causes == ("external_delay",)
    assert "후보 원인: external_delay" in verdict.message
    assert {"log/e3", "log/e4"} <= set(verdict.evidence)


def test_extra_registration_keeps_the_needs_of_the_named_one(tmp_path: Path) -> None:
    """Was `accept · user_input` with no needs: r2's cause wiped r1's missing lookup.

    The quote names r2 here, so validation passes; the rules must still not accept.
    """
    text = TEXT.replace("r1 신청자가", "r1 신청자가 (r2 신청자도)")
    body = TWO_REGISTRATIONS.replace(TEXT, text)
    r2 = ("about_registration", "r2", "r2 신청자")
    verdict = run_triage(scenario(tmp_path, body, PAYMENT, R1, r2), FakeInterpreter())
    assert outcome(verdict) == (VerdictKind.ASK, None, ("payment_lookup",))
    assert verdict.causes == ("user_input",)


def test_cause_still_settles_the_needs_of_its_own_registration_and_topic(tmp_path: Path) -> None:
    """r2 alone: its mismatch is the cause, and its own missing lookup does not block it."""
    text = TEXT.replace("r1", "r2")
    body = TWO_REGISTRATIONS.replace(TEXT, text)
    r2 = ("about_registration", "r2", "r2 신청자")
    verdict = run_triage(scenario(tmp_path, body, PAYMENT, r2), FakeInterpreter())
    assert outcome(verdict) == (VerdictKind.ACCEPT, "user_input", ())


# --- (c) a missing record does not confirm a cause ---------------------------------------

DEADLINE = ("asks_about", "deadline", "은행에서 거절됐대요")
ATTEMPT = (
    "{ id: e1, at: 2026-11-02T11:00:00+09:00, kind: payment_attempt, registration: r1,"
    " attrs: { result: rejected } }"
)
ISSUED = (
    "{ id: e1, at: 2026-11-01T10:00:01+09:00, kind: account_issued, registration: r1,"
    " attrs: { digits: 14 } }"
)


def entered(digits: int) -> str:
    return (
        "{ id: e2, at: 2026-11-01T11:00:00+09:00, kind: account_entered, registration: r1,"
        f" attrs: {{ digits: {digits} }} }}"
    )


def test_policy_default_deadline_asks_for_the_due_record(tmp_path: Path) -> None:
    """Was `accept · expired` on the policy's 24 hours alone (pending 11-01 10:00, attempt
    11-02 11:00). A deadline extension that was never ingested would make that wrong."""
    verdict = one(tmp_path, PENDING, ATTEMPT, DEADLINE, R1)
    assert outcome(verdict) == (VerdictKind.ASK, None, ("payment_due",))
    assert verdict.causes == () and "rule/due_time" not in verdict.evidence


def test_logged_extension_shows_the_attempt_was_on_time(tmp_path: Path) -> None:
    due = "{ id: e2, at: 2026-11-03T23:59:00+09:00, kind: payment_due, registration: r1 }"
    verdict = one(tmp_path, PENDING, f"{ATTEMPT}, {due}", DEADLINE, R1)
    assert outcome(verdict) == (VerdictKind.ASK, None, ())


def test_logged_deadline_still_confirms_expired(tmp_path: Path) -> None:
    due = "{ id: e2, at: 2026-11-02T10:00:00+09:00, kind: payment_due, registration: r1 }"
    verdict = one(tmp_path, PENDING, f"{ATTEMPT}, {due}", DEADLINE, R1)
    assert outcome(verdict) == (VerdictKind.ACCEPT, "expired", ())
    assert {"log/e1", "log/e2"} <= set(verdict.evidence)


def test_confirmed_without_payment_record_asks_for_the_lookup(tmp_path: Path) -> None:
    verdict = one(tmp_path, CONFIRMED, f"{ISSUED}, {entered(14)}", PAYMENT, R1)
    assert outcome(verdict) == (VerdictKind.ASK, None, ("payment_lookup",))


def test_another_cause_does_not_withdraw_the_suspected_bug_lookup(tmp_path: Path) -> None:
    """Was `accept · user_input`: the mismatch wiped type 5's `payment_lookup` request."""
    verdict = one(tmp_path, CONFIRMED, f"{ISSUED}, {entered(13)}", PAYMENT, R1)
    assert outcome(verdict) == (VerdictKind.ASK, None, ("payment_lookup",))
    assert verdict.causes == ("user_input",)
