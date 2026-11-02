"""The report and triage commands run end to end on every synthetic scenario."""

from pathlib import Path

import pytest

from event_ops_engine.cli import main, report, triage
from tests.conftest import REPO, SCENARIOS

NAMES = sorted(path.stem for path in SCENARIOS.glob("*.yaml"))
TRIAGE = SCENARIOS / "triage"
QUESTIONS = sorted(path.stem for path in TRIAGE.glob("*.yaml"))


@pytest.mark.parametrize("name", NAMES)
def test_report_prints_status_and_decisions(name: str) -> None:
    lines = report(SCENARIOS / f"{name}.yaml")
    assert lines[0].startswith("[회차 ")
    assert any("홍보" in line or "확인 요청" in line for line in lines)


def test_main_returns_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["report", str(SCENARIOS / "ratio.yaml")]) == 0
    out = capsys.readouterr().out
    assert "[회차 s4a]" in out and "권고 없음" in out
    assert "[회차 s4b]" in out and "홍보 보류" in out


@pytest.mark.parametrize("name", QUESTIONS)
def test_triage_prints_verdict_and_matches_expectation(name: str) -> None:
    lines, matched = triage(TRIAGE / f"{name}.yaml")
    assert lines[0].startswith("[문의 ") and lines[1].startswith("  판정: ")
    assert matched and lines[-1].endswith("일치")


def test_triage_main_reports_mismatch_with_exit_code_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = (TRIAGE / "account-length.yaml").read_text(encoding="utf-8")
    wrong = tmp_path / "wrong.yaml"
    wrong.write_text(
        source.replace("policy: ../../../../", f"policy: {REPO}/").replace(
            "expected: { kind: accept, cause: user_input, needs: [] }", "expected: { kind: ask }"
        ),
        encoding="utf-8",
    )
    assert main(["triage", str(wrong), "--trace"]) == 1
    out = capsys.readouterr().out
    assert "불일치" in out and "ACT: dry run" in out


def test_triage_main_returns_zero_on_match(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["triage", str(TRIAGE / "delivery-timeout.yaml")]) == 0
    assert "원인 확정 (accept) · 원인: external_delay" in capsys.readouterr().out
