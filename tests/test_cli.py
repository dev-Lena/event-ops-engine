"""The report command runs end to end on every synthetic scenario."""

import pytest

from event_ops_engine.cli import main, report
from tests.conftest import SCENARIOS

NAMES = sorted(path.stem for path in SCENARIOS.glob("*.yaml"))


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
