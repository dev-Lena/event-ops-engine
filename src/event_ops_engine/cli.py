"""Layer: features. `event-ops report <scenario.yaml>` prints capacity status and promotion
decisions for every session; `event-ops triage <scenario.yaml>` prints the verdict for the
scenario's question. Output is for operators, in Korean (docs/glossary.md)."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .capacity import SessionStatus, capacity_status
from .decision import Decision, Verdict, VerdictKind
from .engine import Engine
from .facts import scenario_facts
from .harness import differences, run_triage
from .interpreter import ClaudeCliInterpreter, FakeInterpreter, Interpreter
from .loader import load_scenario, load_triage_scenario
from .model import TriageScenario
from .promotion import promotion_decisions

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


def format_status(status: SessionStatus) -> list[str]:
    lines = [
        f"[회차 {status.session}] 정원 {status.capacity} · 확정 {status.filled} · "
        f"입금 대기 {status.pending} · 남은 자리 {status.remaining_seats}"
        + (" · 마감" if status.is_full else "")
    ]
    for value in status.values:
        target = f"{value.lo}~{value.hi}" if value.lo is not None else "목표 없음"
        extra = f" · 부족 {value.gap}" if value.gap else ""
        extra += " · 목표 충족" if value.is_full else ""
        lines.append(
            f"  {value.dim}={value.value}: 확정 {value.filled} · 대기 {value.pending} · "
            f"목표 {target}{extra}"
        )
    for review in status.needs_review:
        lines.append(f"  확인 요청: {review.message}")
    return lines


def format_decision(decision: Decision) -> str:
    label = {"recommend": "홍보 권고", "hold": "홍보 보류", "ask": "확인 요청"}[decision.kind]
    return (
        f"  {label}: {decision.message} (이유: {', '.join(decision.reasons)}; "
        f"근거: {', '.join(decision.evidence)})"
    )


def report(scenario_path: Path) -> list[str]:
    scenario = load_scenario(scenario_path)
    lines: list[str] = []
    with Engine() as engine:
        engine.load(scenario_facts(scenario))
        statuses = capacity_status(scenario, engine)
        decisions = promotion_decisions(scenario, engine)
    for status in statuses:
        lines.extend(format_status(status))
        own = [d for d in decisions if d.session == status.session]
        lines.extend(format_decision(d) for d in own)
        if not own:
            lines.append("  홍보 판단: 권고 없음")
    return lines


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
        head += " · 더 필요한 사실: " + ", ".join(verdict.needs)
    lines += [head, f"  설명: {verdict.message}", "  근거: " + ", ".join(verdict.evidence)]
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


def triage(
    scenario_path: Path, interpreter: str = "fake", trace: bool = False
) -> tuple[list[str], bool]:
    scenario = load_triage_scenario(scenario_path)
    verdict = run_triage(scenario, INTERPRETERS[interpreter]())
    return format_verdict(scenario, verdict, trace)


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
    args = parser.parse_args(argv)
    if args.command == "report":
        print("\n".join(report(args.scenario)))
        return 0
    if args.command == "triage":
        lines, matched = triage(args.scenario, args.interpreter, args.trace)
        print("\n".join(lines))
        return 0 if matched else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
