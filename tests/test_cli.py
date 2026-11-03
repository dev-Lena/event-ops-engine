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


# --- evidence tiers, repeat runs, preflight (#60 · #61) -------------------------------------


def test_triage_groups_evidence_by_trust_tier() -> None:
    lines, _ = triage(TRIAGE / "seat-full.yaml")
    tiers = [line.split(":")[0].strip() for line in lines if line.strip().startswith("근거 ·")]
    assert tiers == ["근거 · 규칙 추론", "근거 · LLM 제안 · 검증 통과"]


def test_evidence_lines_keep_tier_order_and_unknown_prefixes() -> None:
    from event_ops_engine.cli import evidence_lines

    lines = evidence_lines(["candidate/q/x", "odd/1", "log/e1", "question/q"])
    assert [line.split(":")[0].strip() for line in lines] == [
        "근거 · 원본 사실",
        "근거 · LLM 제안 · 검증 통과",
        "근거 · 질문",
        "근거 · 기타",
    ]


def test_repeat_runs_report_agreement(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["triage", str(TRIAGE / "account-length.yaml"), "--runs", "4"]) == 0
    assert "반복 실행 4회: accept · user_input 4회 / 일치율 100%" in capsys.readouterr().out


def test_unstable_interpreter_shows_the_spread_and_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import event_ops_engine.cli as cli
    from event_ops_engine.interpreter import FakeInterpreter, InterpretationError

    class Flaky(FakeInterpreter):
        calls = 0

        def interpret(self, question, context):  # type: ignore[no-untyped-def]
            Flaky.calls += 1
            if Flaky.calls % 2 == 0:
                raise InterpretationError("flaky")
            return super().interpret(question, context)

    monkeypatch.setitem(cli.INTERPRETERS, "fake", Flaky)
    assert main(["triage", str(TRIAGE / "account-length.yaml"), "--runs", "4"]) == 1
    out = capsys.readouterr().out
    assert "accept · user_input 2회, reject 2회 / 일치율 50%" in out


def test_logged_out_claude_cli_stops_before_running(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import event_ops_engine.cli as cli

    monkeypatch.setattr(cli, "preflight", lambda: "claude exited 1: not logged in")
    code = main(["triage", str(TRIAGE / "account-length.yaml"), "--interpreter", "claude"])
    assert code == 2
    assert "claude login" in capsys.readouterr().err


def test_fake_runs_skip_the_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    import event_ops_engine.cli as cli

    def boom() -> str:
        raise AssertionError("preflight must not run for fake interpreters")

    monkeypatch.setattr(cli, "preflight", boom)
    assert main(["report", str(SCENARIOS / "ratio.yaml")]) == 0
