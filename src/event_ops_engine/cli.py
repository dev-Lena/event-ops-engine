"""Layer: features. `event-ops report <scenario.yaml>` prints capacity status and promotion
decisions for every session; `event-ops triage <scenario.yaml>` prints the verdict for the
scenario's question, its evidence by trust tier, and with `--runs N` how often repeated runs
agree. Output is for operators, in Korean (docs/glossary.md)."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from .capacity import SessionStatus, capacity_status
from .decision import Decision, Verdict, VerdictKind
from .engine import Engine
from .facts import scenario_facts
from .harness import differences, needs_label, run_triage
from .interpreter import ClaudeCliInterpreter, FakeInterpreter, Interpreter, preflight
from .loader import load_scenario, load_triage_scenario
from .model import TriageScenario
from .normalizer import NORMALIZERS, normalize_members
from .promotion import cutoff_hours, promotion_decisions, promotion_stopped

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


def report(scenario_path: Path, normalizer: str = "fake") -> list[str]:
    loaded = load_scenario(scenario_path)
    scenario = normalize_members(loaded, NORMALIZERS[normalizer](loaded))
    lines: list[str] = []
    with Engine() as engine:
        engine.load(scenario_facts(scenario))
        statuses = capacity_status(scenario, engine)
        decisions = promotion_decisions(scenario, engine)
        stopped = {
            s.id: cutoff_hours(engine, s.id)
            for s in scenario.sessions
            if promotion_stopped(engine, s.id)
        }
    for status in statuses:
        lines.extend(format_status(status))
        own = [d for d in decisions if d.session == status.session]
        if status.session in stopped:
            hours = stopped[status.session]
            lines.append(f"  홍보 중단: 시작 {hours}시간 전이 지나 홍보 권고를 내지 않습니다.")
        lines.extend(format_decision(d) for d in own)
        if not own and status.session not in stopped:
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


def triage(
    scenario_path: Path,
    interpreter: str = "fake",
    trace: bool = False,
    normalizer: str = "fake",
    runs: int = 1,
) -> tuple[list[str], bool]:
    """Lines and whether every run matched the scenario's expectation (True if none)."""
    loaded = load_triage_scenario(scenario_path)
    scenario = normalize_members(loaded, NORMALIZERS[normalizer](loaded))
    chosen = INTERPRETERS[interpreter]()
    # Normalization runs once above: repeat runs measure interpreter variance only.
    verdicts = [run_triage(scenario, chosen) for _ in range(runs)]
    lines, matched = format_verdict(scenario, verdicts[0], trace)
    if len(verdicts) > 1:
        lines += agreement_lines(verdicts)
        if scenario.expected is not None:
            matched = all(not differences(v, scenario.expected) for v in verdicts)
    return lines, matched


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
        print("\n".join(report(args.scenario, args.normalizer)))
        return 0
    if args.command == "triage":
        lines, matched = triage(
            args.scenario, args.interpreter, args.trace, args.normalizer, args.runs
        )
        print("\n".join(lines))
        return 0 if matched else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
