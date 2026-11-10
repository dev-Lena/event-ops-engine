"""Layer: features. `event-ops report <scenario.yaml>` prints capacity status and promotion
decisions for every session; `event-ops triage <scenario.yaml>` prints the verdict for the
scenario's question, its evidence by trust tier, and with `--runs N` how often repeated runs
agree. Output is for operators, in Korean (docs/glossary.md). `--json` prints the same results
as a versioned structure for other systems (`REPORT_SCHEMA`, `TRIAGE_SCHEMA`, #85)."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .capacity import AgeGroup, SessionStatus, ValueStatus, capacity_status
from .decision import Decision, Verdict, VerdictKind
from .engine import Engine
from .facts import scenario_facts
from .harness import differences, needs_label, run_triage
from .interpreter import ClaudeCliInterpreter, FakeInterpreter, Interpreter, preflight
from .loader import load_scenario, load_triage_scenario
from .model import DIM_COMBO, DIM_GENDER, Combos, Scenario, TriageScenario
from .normalizer import NORMALIZERS, normalize_members
from .policy import resolve_combos
from .promotion import cutoff_hours, promotion_decisions, promotion_stopped

REPORT_SCHEMA = "event-ops/report@1"
TRIAGE_SCHEMA = "event-ops/triage@1"
"""Version tags of the `--json` output. Any field change bumps the number (#85)."""

VERDICT_LABELS: dict[VerdictKind, str] = {
    VerdictKind.ACCEPT: "원인 확정",
    VerdictKind.ASK: "확인 요청",
    VerdictKind.ABSTAIN: "판정 보류",
    VerdictKind.REJECT: "해석 거부",
}
INTERPRETERS: dict[str, type[Interpreter]] = {
    "fake": FakeInterpreter,
    "claude": ClaudeCliInterpreter,
}
EVIDENCE_TIERS: tuple[tuple[str, str], ...] = (
    ("log/", "명시 사실"),
    ("rule/", "추론 사실"),
    ("candidate/", "LLM 추출 후보(검증 통과)"),
    ("question/", "질문"),
)
"""How far each evidence id can be trusted, most first: an asserted fact (recorded), an
inferred fact (derived by the rules), an LLM-extracted candidate that passed validation.
"Cannot confirm" has no tier; it is the `ask` / `abstain` verdict itself (docs/design.md 13)."""


def _counts(value: ValueStatus) -> str:
    target = f"{value.lo}~{value.hi}" if value.lo is not None else "목표 없음"
    extra = f" · 부족 {value.gap}" if value.gap else ""
    extra += " · 목표 충족" if value.is_full else ""
    return f"확정 {value.filled} · 대기 {value.pending} · 목표 {target}{extra}"


AGE_POOL_LABELS = {"occupying": "확정·대기", "applied": "신청 접수"}


def _ages(group: AgeGroup) -> str:
    """'26 · 27 · 33 — 26~33세, 폭 7살' plus how many were left out for a missing birth year."""
    if group.ages:
        span = f"{group.low}세" if group.low == group.high else f"{group.low}~{group.high}세"
        text = f"{' · '.join(str(age) for age in group.ages)} — {span}, 폭 {group.spread}살"
    else:
        text = "없음"
    if group.unknown:
        text += f" · 출생연도 없음 {group.unknown}명 제외"
    return text


def format_status(status: SessionStatus, combos: Combos) -> list[str]:
    """Session status lines. Under each gender's line come its ages per pool when the event
    keeps a similar age (#91), then its combinations (#32), youngest first. A gender without
    a line of its own gets both at the top level. `combos` is the session's
    (`policy.resolve_combos`): every `combo` value in `status` is defined there.
    """
    lines = [
        f"[회차 {status.session}] 정원 {status.capacity} · 확정 {status.filled} · "
        f"입금 대기 {status.pending} · 남은 자리 {status.remaining_seats}"
        + (" · 마감" if status.is_full else "")
    ]
    nested: dict[str, list[ValueStatus]] = {}
    for value in status.values:
        if value.dim == DIM_COMBO:
            nested.setdefault(combos[value.value].gender.value, []).append(value)
    ages: dict[str, list[AgeGroup]] = {}
    for group in status.ages:
        ages.setdefault(group.gender, []).append(group)

    def children(gender: str, indent: str, prefix: str) -> list[str]:
        """Age lines then combination lines of one gender, each emitted once."""
        out = [
            f"{indent}{prefix}나이(연 나이) {AGE_POOL_LABELS[group.pool]}: {_ages(group)}"
            for group in ages.pop(gender, [])
        ]
        marker = "└ " if indent == "    " else ""
        out.extend(
            f"{indent}{marker}{combos[child.value].label}: {_counts(child)}"
            for child in sorted(nested.pop(gender, []), key=lambda v: combos[v.value].age)
        )
        return out

    for value in status.values:
        if value.dim == DIM_COMBO:
            continue
        lines.append(f"  {value.dim}={value.value}: {_counts(value)}")
        if value.dim == DIM_GENDER:
            lines.extend(children(value.value, "    ", ""))
    for gender in sorted(set(nested) | set(ages)):
        lines.extend(children(gender, "  ", f"{gender} "))
    for review in status.needs_review:
        lines.append(f"  확인 요청: {review.message}")
    return lines


def format_decision(decision: Decision) -> str:
    label = {
        "recommend": "홍보 권고",
        "hold": "홍보 보류",
        "ask": "확인 요청",
        "cap": "잠정 마감 권고",
    }[decision.kind]
    return (
        f"  {label}: {decision.message} (이유: {', '.join(decision.reasons)}; "
        f"근거: {', '.join(decision.evidence)})"
    )


@dataclasses.dataclass(frozen=True)
class ReportResult:
    scenario: Scenario
    statuses: list[SessionStatus]
    decisions: list[Decision]
    stopped: dict[str, int]
    """Sessions past their promotion cutoff -> the cutoff hours (#52)."""


def run_report(scenario_path: Path, normalizer: str = "fake") -> ReportResult:
    loaded = load_scenario(scenario_path)
    scenario = normalize_members(loaded, NORMALIZERS[normalizer](loaded))
    with Engine() as engine:
        engine.load(scenario_facts(scenario))
        statuses = capacity_status(scenario, engine)
        decisions = promotion_decisions(scenario, engine)
        stopped = {
            s.id: cutoff_hours(engine, s.id)
            for s in scenario.sessions
            if promotion_stopped(engine, s.id)
        }
    return ReportResult(scenario, statuses, decisions, stopped)


def report(scenario_path: Path, normalizer: str = "fake") -> list[str]:
    result = run_report(scenario_path, normalizer)
    decisions, stopped = result.decisions, result.stopped
    lines: list[str] = []
    for status in result.statuses:
        session = result.scenario.session(status.session)
        lines.extend(format_status(status, resolve_combos(result.scenario.policy, session)))
        own = [d for d in decisions if d.session == status.session]
        if status.session in stopped:
            hours = stopped[status.session]
            lines.append(f"  홍보 중단: 시작 {hours}시간 전이 지나 홍보 권고를 내지 않습니다.")
        lines.extend(format_decision(d) for d in own)
        if not own and status.session not in stopped:
            lines.append("  홍보 판단: 권고 없음")
    return lines


def combo_json(combos: Combos) -> dict[str, dict[str, Any]]:
    """What each `combo` value in `values` means (#32). Added field, so still `report@1`."""
    return {
        name: {"gender": combo.gender.value, "age": list(combo.age), "label": combo.label}
        for name, combo in sorted(combos.items())
    }


def report_json(result: ReportResult) -> dict[str, Any]:
    return {
        "schema": REPORT_SCHEMA,
        "now": result.scenario.now.isoformat(),
        "sessions": [
            {
                "session": status.session,
                "capacity": status.capacity,
                "filled": status.filled,
                "pending": status.pending,
                "remaining_seats": status.remaining_seats,
                "is_full": status.is_full,
                "promotion_stopped": status.session in result.stopped,
                "values": [dataclasses.asdict(value) for value in status.values],
                "combos": combo_json(
                    resolve_combos(result.scenario.policy, result.scenario.session(status.session))
                ),
                "needs_review": [d.model_dump(mode="json") for d in status.needs_review],
                # Added field (#91), so still report@1. Ages only, never registration ids.
                "ages": [dataclasses.asdict(group) for group in status.ages],
                "decisions": [
                    d.model_dump(mode="json")
                    for d in result.decisions
                    if d.session == status.session
                ],
            }
            for status in result.statuses
        ],
    }


def format_verdict(
    scenario: TriageScenario, verdict: Verdict, trace: bool = False
) -> tuple[list[str], bool]:
    """Lines for one verdict and whether it matches the scenario's expectation (True if none)."""
    lines = [f"[문의 {verdict.question}] {scenario.question.text}"]
    head = f"  판정: {VERDICT_LABELS[verdict.kind]} ({verdict.kind})"
    if verdict.cause:
        head += f" · 원인: {verdict.cause}"
    elif verdict.causes:
        head += " · 후보 원인: " + ", ".join(verdict.causes)
    if verdict.needs:
        head += " · 더 필요한 사실: " + ", ".join(needs_label(n) for n in verdict.needs)
    lines += [head, f"  설명: {verdict.message}"]
    lines += evidence_lines(verdict.evidence)
    matched = True
    if scenario.expected is not None:
        found = differences(verdict, scenario.expected)
        matched = not found
        lines.append(
            f"  기대 판정: {scenario.expected.kind} · "
            + ("일치" if matched else "불일치 (" + "; ".join(found) + ")")
        )
    if trace:
        lines += [f"  {step}" for step in verdict.trace]
    return lines, matched


def evidence_lines(evidence: Sequence[str]) -> list[str]:
    """One line per trust tier, most trusted first; ids with an unknown prefix go last."""
    lines: list[str] = []
    left = list(evidence)
    for prefix, label in EVIDENCE_TIERS:
        tier = [e for e in left if e.startswith(prefix)]
        if tier:
            lines.append(f"  근거 · {label}: " + ", ".join(tier))
            left = [e for e in left if not e.startswith(prefix)]
    if left:
        lines.append("  근거 · 기타: " + ", ".join(left))
    return lines


def outcome(verdict: Verdict) -> str:
    return " · ".join([verdict.kind, *([verdict.cause] if verdict.cause else [])])


def agreement_lines(verdicts: Sequence[Verdict]) -> list[str]:
    """How often repeated runs gave the same verdict (kind + cause)."""
    counts = Counter(outcome(v) for v in verdicts)
    top = counts.most_common(1)[0][1]
    spread = ", ".join(f"{key} {n}회" for key, n in counts.most_common())
    return [f"  반복 실행 {len(verdicts)}회: {spread} / 일치율 {top * 100 // len(verdicts)}%"]


def triage_runs(
    scenario_path: Path, interpreter: str = "fake", normalizer: str = "fake", runs: int = 1
) -> tuple[TriageScenario, list[Verdict], bool]:
    """The scenario, one verdict per run, and whether every run matched the expectation."""
    loaded = load_triage_scenario(scenario_path)
    scenario = normalize_members(loaded, NORMALIZERS[normalizer](loaded))
    chosen = INTERPRETERS[interpreter]()
    # Normalization runs once above: repeat runs measure interpreter variance only.
    verdicts = [run_triage(scenario, chosen) for _ in range(runs)]
    expected = scenario.expected
    matched = expected is None or all(not differences(v, expected) for v in verdicts)
    return scenario, verdicts, matched


def triage(
    scenario_path: Path,
    interpreter: str = "fake",
    trace: bool = False,
    normalizer: str = "fake",
    runs: int = 1,
) -> tuple[list[str], bool]:
    """Lines and whether every run matched the scenario's expectation (True if none)."""
    scenario, verdicts, matched = triage_runs(scenario_path, interpreter, normalizer, runs)
    lines, _ = format_verdict(scenario, verdicts[0], trace)
    if len(verdicts) > 1:
        lines += agreement_lines(verdicts)
    return lines, matched


def triage_json(
    scenario: TriageScenario, verdicts: Sequence[Verdict], matched: bool, trace: bool = False
) -> dict[str, Any]:
    exclude = None if trace else {"trace"}
    return {
        "schema": TRIAGE_SCHEMA,
        "question": scenario.question.id,
        "matched": matched,
        "verdicts": [v.model_dump(mode="json", exclude=exclude) for v in verdicts],
    }


def print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("1 이상이어야 합니다")
    return value


def uses_claude(args: argparse.Namespace) -> bool:
    return "claude" in (getattr(args, "interpreter", None), getattr(args, "normalizer", None))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="event-ops", description="모임 운영 판단 엔진")
    sub = parser.add_subparsers(dest="command", required=True)
    report_parser = sub.add_parser("report", help="회차 현황과 홍보 판단을 출력")
    report_parser.add_argument("scenario", type=Path, help="시나리오 YAML 경로")
    triage_parser = sub.add_parser("triage", help="문의 시나리오의 판정을 출력")
    triage_parser.add_argument("scenario", type=Path, help="문의 시나리오 YAML 경로")
    triage_parser.add_argument(
        "--interpreter",
        choices=sorted(INTERPRETERS),
        default="fake",
        help="fake: 시나리오의 canned 해석 (기본), claude: Claude Code CLI (`claude -p`)",
    )
    triage_parser.add_argument("--trace", action="store_true", help="단계별 trace도 출력")
    triage_parser.add_argument(
        "--runs",
        type=positive_int,
        default=1,
        help="같은 질문을 N번 판정해 결과 분포와 일치율을 출력 (실제 해석기 안정성 확인용). "
        "정규화는 한 번만 하므로 해석기의 변동만 잰다. --trace는 첫 실행만 보인다",
    )
    for subparser in (report_parser, triage_parser):
        subparser.add_argument(
            "--normalizer",
            choices=sorted(NORMALIZERS),
            default="fake",
            help="직군 정규화기. fake: 시나리오의 canned_job_groups (기본), claude: Claude Code CLI",
        )
        subparser.add_argument(
            "--json",
            action="store_true",
            help="사람용 문장 대신 다른 시스템이 읽을 JSON으로 출력 (형식: README '결과 JSON')",
        )
    args = parser.parse_args(argv)
    if uses_claude(args):
        problem = preflight()
        if problem is not None:
            print(
                f"Claude CLI를 쓸 수 없습니다: {problem}\n"
                "터미널에서 `claude login`을 실행한 뒤 다시 시도하세요.",
                file=sys.stderr,
            )
            return 2
    if args.command == "report":
        if args.json:
            print_json(report_json(run_report(args.scenario, args.normalizer)))
        else:
            print("\n".join(report(args.scenario, args.normalizer)))
        return 0
    if args.command == "triage":
        if args.json:
            scenario, verdicts, matched = triage_runs(
                args.scenario, args.interpreter, args.normalizer, args.runs
            )
            print_json(triage_json(scenario, verdicts, matched, args.trace))
        else:
            lines, matched = triage(
                args.scenario, args.interpreter, args.trace, args.normalizer, args.runs
            )
            print("\n".join(lines))
        return 0 if matched else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
