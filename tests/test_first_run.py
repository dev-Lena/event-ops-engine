"""First run for package installs (#110): the packaged samples and the engine-missing message.

The installed-wheel side (samples inside the package, run from an empty folder) is checked by
`make wheel-smoke`, which CI runs."""

import sys

import pytest

from event_ops_engine.cli import main
from event_ops_engine.engine import Engine
from event_ops_engine.loader import samples_dir
from tests.conftest import SCENARIOS


def test_samples_dir_in_a_checkout_is_the_repo_folder() -> None:
    assert samples_dir() == SCENARIOS
    assert (samples_dir() / "triage" / "account-length.yaml").is_file()


def test_samples_command_prints_a_folder_report_can_read(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["samples"]) == 0
    folder = capsys.readouterr().out.strip()
    assert main(["report", f"{folder}/pair-mixed.yaml"]) == 0
    assert "잠정 마감 권고" in capsys.readouterr().out


def test_a_missing_engine_says_how_to_build_it(monkeypatch: pytest.MonkeyPatch) -> None:
    class Broken:
        """Stands in for a pyrewire whose import fails to load libwirelog."""

        def __getattr__(self, name: str) -> object:
            if name == "EasySession":
                raise OSError("Could not find libwirelog")
            raise AttributeError(name)

    monkeypatch.setitem(sys.modules, "pyrewire", Broken())
    monkeypatch.setenv("WIRELOG_LIB", "/nonexistent/libwirelog.1.dylib")
    with pytest.raises(OSError) as caught:
        Engine()
    text = str(caught.value)
    assert "make engine" in text and "export WIRELOG_LIB=" in text
    assert "WIRELOG_LIB=/nonexistent/libwirelog.1.dylib (그 경로에 파일이 없습니다)" in text
    assert "Could not find libwirelog" in str(caught.value.__cause__)
