"""Layer: features. Module ① harness: ADAPT → INTERPRET → REASON → DECIDE → ACT.

The interpreter proposes candidate facts; this module validates them, lets the rules derive
`in_scope` / `cause` / `needs`, and applies the decision contract. ACT is a dry run: the
verdict, its evidence and a per-stage trace are returned, nothing is executed.
See docs/design.md 13.
"""

from __future__ import annotations

from .decision import Verdict, VerdictKind
from .engine import Engine
from .facts import (
    CANDIDATE_RELATIONS,
    TOPICS,
    Facts,
    candidate_id,
    evidence_id,
    squash,
    triage_facts,
)
from .interpreter import InterpretationError, InterpretContext, Interpreter
from .model import CandidateFact, ExpectedVerdict, Interpretation, TriageScenario

NEEDS_VERIFIER: dict[str, str] = {
    "provider_lookup": "외부: 발송 업체 로그",
    "payment_lookup": "외부: 결제 업체 입금 내역",
    "account_issued": "내부: 계좌 발급 기록",
    "account_entered": "내부: 입금 시도 기록",
    "payment_due": "내부: 선별 · 기한 기록",
    "payment_attempt": "내부: 입금 시도 기록",
    "registration_submitted": "내부: 신청 제출 기록",
    "session": "질문: 어느 회차인지",
    "attribute_value": "질문: 어느 속성 값인지",
    "target": "정책: 그 값의 목표",
}
"""Who can supply each `needs` value: an external provider, internal records, the asker
or the policy. The admin alert is a conservative to-do note; the provider log is the truth."""


def needs_label(what: str) -> str:
    return f"{what} ({NEEDS_VERIFIER[what]})" if what in NEEDS_VERIFIER else what


def validate(
    interpretation: Interpretation,
    scenario: TriageScenario,
    context: InterpretContext | None = None,
) -> list[str]:
    """Problems that make the interpretation unusable (empty list = valid)."""
    context = context or InterpretContext.from_scenario(scenario)
    known = {
        "registration": set(context.registrations),
        "session": set(context.sessions),
        "log": set(context.log_ids),
    }
    question = squash(scenario.question.text)
    problems: list[str] = []
    for fact in interpretation.facts:
        kinds = CANDIDATE_RELATIONS.get(fact.relation)
        if kinds is None:
            problems.append(f"unknown relation {fact.relation}")
            continue
        if len(fact.args) != len(kinds):
            problems.append(
                f"{fact.relation}: expected {len(kinds)} argument(s), got {len(fact.args)}"
            )
            continue
        if fact.provenance.source != "question":
            problems.append(f"{fact.relation}: provenance source must be the question")
        if squash(fact.provenance.quote) not in question:
            problems.append(f"{fact.relation}: quote not found in the question")
        if kinds == ("dim", "value"):
            if (fact.args[0], fact.args[1]) not in context.values:
                problems.append(
                    f"{fact.relation}: unknown attribute value {fact.args[0]}={fact.args[1]}"
                )
        elif kinds != ("topic",) and fact.args[0] not in known[kinds[0]]:
            problems.append(f"{fact.relation}: unknown {kinds[0]} id {fact.args[0]}")
    return problems


def _reject(scenario: TriageScenario, reasons: list[str], trace: list[str]) -> Verdict:
    trace.append("DECIDE: reject")
    trace.append("ACT: dry run, nothing executed")
    return Verdict(
        kind=VerdictKind.REJECT,
        question=scenario.question.id,
        evidence=(evidence_id("question", scenario.question.id),),
        message="해석 결과를 거부했습니다: " + "; ".join(reasons),
        trace=tuple(trace),
    )


def candidate_facts(question_id: str, facts: tuple[CandidateFact, ...]) -> Facts:
    """Engine rows for the candidates, one per distinct (relation, arguments)."""
    rows = Facts()
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for fact in facts:
        key = (fact.relation, fact.args)
        if key not in seen:
            seen.add(key)
            rows.add(fact.relation, question_id, *fact.args)
    return rows


def _dropped_note(dropped: tuple[CandidateFact, ...]) -> str:
    if not dropped:
        return ""
    listed = ", ".join(f"{f.relation} {' '.join(f.args)} ({f.confidence:.2f})" for f in dropped)
    return f" (확신이 낮아 판정에 쓰지 않은 후보: {listed})"


def split_by_confidence(
    facts: tuple[CandidateFact, ...], minimum: float
) -> tuple[tuple[CandidateFact, ...], tuple[CandidateFact, ...]]:
    """(used, dropped): a candidate the interpreter is unsure of never reaches the rules."""
    used = tuple(f for f in facts if f.confidence >= minimum)
    return used, tuple(f for f in facts if f.confidence < minimum)


def decide(
    engine: Engine,
    scenario: TriageScenario,
    candidate_ids: list[str],
    trace: list[str],
    dropped: tuple[CandidateFact, ...] = (),
) -> Verdict:
    q = scenario.question.id
    in_scope = bool(engine.rows("in_scope", q))
    cause_rows = engine.rows("cause", q)
    causes = sorted({str(row[1]) for row in cause_rows})
    # `needs` only matters while no cause is derived; a cause from one event must not drag
    # along "still missing" facts about another.
    needs = [] if causes else sorted({str(row[1]) for row in engine.rows("needs", q)})
    log_ids = {event.id for event in scenario.log}
    # A cause's evidence is a log event id, or the name of the rule-derived fact (an
    # invariant, a module ② relation) when no single log event explains the verdict.
    derived = sorted(
        {
            evidence_id("log" if str(row[2]) in log_ids else "rule", str(row[2]))
            for row in cause_rows
        }
    )
    trace.append(f"REASON: in_scope={in_scope}, causes={causes}, needs={needs}")
    base = tuple(candidate_ids) or (evidence_id("question", q),)

    if not candidate_ids:
        trace.append("DECIDE: ask (no candidate facts)")
        kind, message, evidence = (
            VerdictKind.ASK,
            "질문에서 판정에 쓸 사실을 찾지 못했습니다. 신청 id · 회차 · 무엇이 문제인지 적어 주세요.",
            base,
        )
    elif not in_scope:
        trace.append("DECIDE: abstain (topic not supported)")
        kind, message, evidence = (
            VerdictKind.ABSTAIN,
            "지원하지 않는 문의입니다. 지원 주제: " + ", ".join(TOPICS),
            base,
        )
    elif len(causes) == 1:
        trace.append(f"DECIDE: accept ({causes[0]})")
        kind, message, evidence = (
            VerdictKind.ACCEPT,
            f"원인: {causes[0]}. 근거: " + ", ".join(derived),
            base + tuple(derived),
        )
    elif not causes:
        trace.append("DECIDE: ask (no cause derived)")
        kind, message, evidence = (
            VerdictKind.ASK,
            "판정하려면 더 필요합니다: "
            + (", ".join(needs_label(n) for n in needs) or "유형 규칙 없음 또는 관련 로그 없음"),
            base,
        )
    else:
        trace.append(f"DECIDE: ask (several causes: {causes})")
        kind, message, evidence = (
            VerdictKind.ASK,
            "원인 후보가 여럿입니다. 사람이 가려야 합니다: " + ", ".join(causes),
            base + tuple(derived),
        )
    message += _dropped_note(dropped)
    trace.append("ACT: dry run, nothing executed")
    return Verdict(
        kind=kind,
        question=q,
        cause=causes[0] if kind == VerdictKind.ACCEPT else None,
        causes=tuple(causes),
        needs=tuple(needs),
        evidence=evidence,
        message=message,
        trace=tuple(trace),
    )


def run_triage(
    scenario: TriageScenario, interpreter: Interpreter, engine: Engine | None = None
) -> Verdict:
    """Run the five stages for the scenario's question.

    Supplies its own engine unless given one. A given engine is left as it was found: every
    scenario and candidate fact is retracted afterwards, so one engine can serve many questions.
    """
    if engine is None:
        with Engine() as own:
            return run_triage(scenario, interpreter, own)
    trace: list[str] = []
    facts = triage_facts(scenario)
    candidates = Facts()
    engine.load(facts)
    try:
        trace.append(f"ADAPT: loaded {sum(len(rows) for rows in facts.rows.values())} facts")
        context = InterpretContext.from_scenario(scenario)
        try:
            interpretation = interpreter.interpret(scenario.question, context)
        except InterpretationError as error:
            trace.append(f"INTERPRET: failed ({error})")
            return _reject(scenario, [str(error)], trace)
        trace.append(f"INTERPRET: {len(interpretation.facts)} candidate facts")
        problems = validate(interpretation, scenario, context)
        if problems:
            trace.append(f"INTERPRET: rejected {len(problems)} problems")
            return _reject(scenario, problems, trace)

        used, dropped = split_by_confidence(
            interpretation.facts, scenario.policy.triage.min_candidate_confidence
        )
        if dropped:
            trace.append(f"INTERPRET: dropped {len(dropped)} low-confidence candidates")
        candidates = candidate_facts(scenario.question.id, used)
        engine.load(candidates)
        candidate_ids = sorted({candidate_id(scenario.question.id, f) for f in used})
        return decide(engine, scenario, candidate_ids, trace, dropped)
    finally:
        engine.retract(candidates)
        engine.retract(facts)


def differences(verdict: Verdict, expected: ExpectedVerdict) -> list[str]:
    """How the verdict departs from what the scenario expects (empty list = as expected).

    A field the scenario leaves out (`cause: null`, `needs: null`) is not compared;
    `needs: []` asserts that nothing is missing.
    """
    found: list[str] = []
    if verdict.kind != expected.kind:
        found.append(f"kind: expected {expected.kind}, got {verdict.kind}")
    if expected.cause is not None and verdict.cause != expected.cause:
        found.append(f"cause: expected {expected.cause}, got {verdict.cause}")
    if expected.needs is not None and tuple(sorted(expected.needs)) != verdict.needs:
        found.append(f"needs: expected {list(expected.needs)}, got {list(verdict.needs)}")
    return found
