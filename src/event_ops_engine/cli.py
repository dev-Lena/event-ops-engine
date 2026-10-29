"""Layer: features. `event-ops report <scenario.yaml>` prints capacity status and promotion
decisions for every session. Output is for operators, in Korean (docs/glossary.md)."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .capacity import SessionStatus, capacity_status
from .decision import Decision
from .engine import Engine
from .facts import scenario_facts
from .loader import load_scenario
from .promotion import promotion_decisions


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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="event-ops", description="모임 운영 판단 엔진")
    sub = parser.add_subparsers(dest="command", required=True)
    report_parser = sub.add_parser("report", help="회차 현황과 홍보 판단을 출력")
    report_parser.add_argument("scenario", type=Path, help="시나리오 YAML 경로")
    args = parser.parse_args(argv)
    if args.command == "report":
        print("\n".join(report(args.scenario)))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
