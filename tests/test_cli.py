"""The report and triage commands run end to end on every synthetic scenario."""

from pathlib import Path
from typing import Any

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
    assert tiers == ["근거 · 추론 사실", "근거 · LLM 추출 후보(검증 통과)"]


def test_evidence_lines_keep_tier_order_and_unknown_prefixes() -> None:
    from event_ops_engine.cli import evidence_lines

    lines = evidence_lines(["candidate/q/x", "odd/1", "log/e1", "question/q"])
    assert [line.split(":")[0].strip() for line in lines] == [
        "근거 · 명시 사실",
        "근거 · LLM 추출 후보(검증 통과)",
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

        def interpret(self, question, context):
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


@pytest.mark.parametrize("runs", ["0", "-2"])
def test_runs_must_be_positive(runs: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stop:
        main(["triage", str(TRIAGE / "account-length.yaml"), "--runs", runs])
    assert stop.value.code == 2 and "1 이상" in capsys.readouterr().err


def write_scenario(tmp_path: Path, start_time: str) -> Path:
    policy = REPO / "policy" / "events" / "synthetic-example.yaml"
    path = tmp_path / "cutoff.yaml"
    path.write_text(
        f"policy: '{policy}'\n"
        "now: 2026-11-10T18:00:00+09:00\n"
        f"sessions:\n  - {{ id: s9, date: 2026-11-10, start_time: {start_time} }}\n",
        encoding="utf-8",
    )
    return path


def test_report_says_promotion_stopped_after_the_cutoff(tmp_path: Path) -> None:
    lines = report(write_scenario(tmp_path, '"19:00"'))
    assert "  홍보 중단: 시작 2시간 전이 지나 홍보 권고를 내지 않습니다." in lines
    assert "  홍보 판단: 권고 없음" not in lines


def test_past_session_gets_no_stop_line(tmp_path: Path) -> None:
    path = write_scenario(tmp_path, '"19:00"')
    path.write_text(path.read_text().replace("2026-11-10T18", "2026-11-11T18"), encoding="utf-8")
    assert not any("홍보 중단" in line for line in report(path))


@pytest.mark.parametrize(
    ("raw", "problem"),
    [("19:00", "must be quoted"), ('"19:00+09:00"', "drop the offset")],
)
def test_start_time_must_be_quoted_local_text(tmp_path: Path, raw: str, problem: str) -> None:
    # Unquoted 19:00 is the YAML 1.1 integer 1140, which would silently become 00:19:00.
    from pydantic import ValidationError

    from event_ops_engine.loader import load_scenario

    with pytest.raises(ValidationError, match=problem):
        load_scenario(write_scenario(tmp_path, raw))


# --- --json output (#85) -----------------------------------------------------------------


def json_out(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, Any]:
    import json

    code = main(argv)
    return code, json.loads(capsys.readouterr().out)


def test_report_json_carries_the_same_results_as_the_models(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from event_ops_engine.cli import REPORT_SCHEMA, run_report
    from event_ops_engine.decision import Decision

    path = SCENARIOS / "pair-mixed.yaml"
    code, out = json_out(capsys, ["report", str(path), "--json"])
    assert code == 0 and out["schema"] == REPORT_SCHEMA
    assert out["now"] == "2026-11-07T10:00:00+09:00"
    (session,) = out["sessions"]
    result = run_report(path)
    assert session["filled"] == result.statuses[0].filled
    assert session["promotion_stopped"] is False
    decisions = [Decision.model_validate(d) for d in session["decisions"]]
    assert decisions == [d for d in result.decisions if d.session == "s2"]
    assert {d.kind for d in decisions} == {"recommend", "cap"}
    male = next(v for v in session["values"] if v["value"] == "male")
    assert male["gap"] == 4 and male["evidence"]


def test_report_json_marks_a_session_past_its_cutoff(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, out = json_out(capsys, ["report", str(write_scenario(tmp_path, '"19:00"')), "--json"])
    assert out["sessions"][0]["promotion_stopped"] is True


def test_triage_json_round_trips_verdicts_and_keeps_the_exit_code(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from event_ops_engine.cli import TRIAGE_SCHEMA, triage_runs
    from event_ops_engine.decision import Verdict

    path = TRIAGE / "account-length.yaml"
    code, out = json_out(capsys, ["triage", str(path), "--json", "--runs", "2"])
    assert code == 0 and out["schema"] == TRIAGE_SCHEMA and out["matched"] is True
    assert out["question"] == "q1"
    verdicts = [Verdict.model_validate(v) for v in out["verdicts"]]
    _, expected, _ = triage_runs(path, runs=2)
    assert verdicts == [v.model_copy(update={"trace": ()}) for v in expected]
    assert all("trace" not in v for v in out["verdicts"])
    _, traced = json_out(capsys, ["triage", str(path), "--json", "--trace"])
    assert traced["verdicts"][0]["trace"]


def test_triage_json_exits_1_when_the_verdict_differs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = (TRIAGE / "account-length.yaml").read_text(encoding="utf-8")
    assert "kind: accept" in source
    changed = tmp_path / "triage" / "changed.yaml"
    changed.parent.mkdir()
    changed.write_text(
        source.replace("kind: accept", "kind: ask").replace(
            "../../../../policy", str(REPO / "policy")
        ),
        encoding="utf-8",
    )
    code, out = json_out(capsys, ["triage", str(changed), "--json"])
    assert code == 1 and out["matched"] is False
