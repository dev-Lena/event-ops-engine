"""Layer: features. Module ① harness: ADAPT → INTERPRET → REASON → DECIDE → ACT.

The interpreter proposes candidate facts; this module validates them, lets the rules derive
`in_scope` / `cause` / `needs`, and applies the decision contract. ACT is a dry run: the
verdict, its evidence and a per-stage trace are returned, nothing is executed.
See docs/design.md 13.
"""

from __future__ import annotations

from .decision import Verdict, VerdictKind
from .engine import Engine
from .facts import CANDIDATE_RELATIONS, TOPICS, candidate_id, evidence_id, triage_facts
from .interpreter import InterpretationError, InterpretContext, Interpreter
from .model import CandidateFact, Interpretation, TriageScenario


def validate(interpretation: Interpretation, scenario: TriageScenario) -> list[str]:
    """Problems that make the interpretation unusable (empty list = valid)."""
    context = InterpretContext.from_scenario(scenario)
    known = {
        "registration": set(context.registrations),
        "session": set(context.sessions),
        "log": set(context.log_ids),
    }
    problems: list[str] = []
    for fact in interpretation.facts:
        kind = CANDIDATE_RELATIONS.get(fact.relation)
        if kind is None:
            problems.append(f"unknown relation {fact.relation}")
            continue
        if len(fact.args) != 1:
            problems.append(f"{fact.relation}: expected one argument, got {len(fact.args)}")
            continue
        if fact.provenance.source != "question":
            problems.append(f"{fact.relation}: provenance source must be the question")
        if fact.provenance.quote not in scenario.question.text:
            problems.append(f"{fact.relation}: quote not found in the question")
        if kind != "topic" and fact.args[0] not in known[kind]:
            problems.append(f"{fact.relation}: unknown {kind} id {fact.args[0]}")
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


def _insert_candidates(
    engine: Engine, question_id: str, facts: tuple[CandidateFact, ...]
) -> list[str]:
    ids: list[str] = []
    for fact in facts:
        engine.insert(fact.relation, (question_id, fact.args[0]))
        ids.append(candidate_id(question_id, fact))
    return ids


def decide(
    engine: Engine, scenario: TriageScenario, candidate_ids: list[str], trace: list[str]
) -> Verdict:
    q = scenario.question.id
    in_scope = bool(engine.rows("in_scope", q))
    cause_rows = engine.rows("cause", q)
    causes = sorted({str(row[1]) for row in cause_rows})
    needs = sorted({str(row[1]) for row in engine.rows("needs", q)})
    trace.append(f"REASON: in_scope={in_scope}, causes={causes}, needs={needs}")
    base = tuple(candidate_ids) or (evidence_id("question", q),)

    if not in_scope:
        trace.append("DECIDE: abstain (topic not supported)")
        kind, message, evidence = (
            VerdictKind.ABSTAIN,
            "지원하지 않는 문의입니다. 지원 주제: " + ", ".join(TOPICS),
            base,
        )
    elif len(causes) == 1:
        logs = sorted({evidence_id("log", str(row[2])) for row in cause_rows})
        trace.append(f"DECIDE: accept ({causes[0]})")
        kind, message, evidence = (
            VerdictKind.ACCEPT,
            f"원인: {causes[0]}. 근거 로그: " + ", ".join(logs),
            base + tuple(logs),
        )
    elif not causes:
        trace.append("DECIDE: ask (no cause derived)")
        kind, message, evidence = (
            VerdictKind.ASK,
            "판정하려면 더 필요합니다: "
            + (", ".join(needs) or "유형 규칙 없음 또는 관련 로그 없음"),
            base,
        )
    else:
        logs = sorted({evidence_id("log", str(row[2])) for row in cause_rows})
        trace.append(f"DECIDE: ask (several causes: {causes})")
        kind, message, evidence = (
            VerdictKind.ASK,
            "원인 후보가 여럿입니다. 사람이 가려야 합니다: " + ", ".join(causes),
            base + tuple(logs),
        )
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
    """Run the five stages for the scenario's question. Supplies its own engine unless given one."""
    if engine is None:
        with Engine() as own:
            return run_triage(scenario, interpreter, own)
    trace: list[str] = []
    facts = triage_facts(scenario)
    engine.load(facts)
    trace.append(f"ADAPT: loaded {sum(len(rows) for rows in facts.rows.values())} facts")

    try:
        interpretation = interpreter.interpret(
            scenario.question, InterpretContext.from_scenario(scenario)
        )
    except InterpretationError as error:
        trace.append(f"INTERPRET: failed ({error})")
        return _reject(scenario, [str(error)], trace)
    trace.append(f"INTERPRET: {len(interpretation.facts)} candidate facts")
    problems = validate(interpretation, scenario)
    if problems:
        trace.append(f"INTERPRET: rejected {len(problems)} problems")
        return _reject(scenario, problems, trace)

    candidate_ids = _insert_candidates(engine, scenario.question.id, interpretation.facts)
    return decide(engine, scenario, candidate_ids, trace)
