"""README sample outputs are real: every `event-ops` command block is run and compared."""

import re

import pytest

from event_ops_engine.cli import main
from tests.conftest import REPO

README = REPO / "README.md"
BLOCK = re.compile(r"```bash\n(event-ops [^\n]+)\n```\n\n```\n(.*?)```", re.DOTALL)


def samples() -> list[tuple[str, str]]:
    return BLOCK.findall(README.read_text(encoding="utf-8"))


def line_matches(expected: str, actual: str) -> bool:
    """`...` in the README stands for the rest of the line."""
    head, ellipsis, _ = expected.partition("...")
    return actual.startswith(head) if ellipsis else actual == expected


def test_readme_has_samples_for_both_commands() -> None:
    commands = [command for command, _ in samples()]
    assert any(c.startswith("event-ops report ") for c in commands)
    assert any(c.startswith("event-ops triage ") for c in commands)


@pytest.mark.parametrize("command, expected", samples(), ids=[c for c, _ in samples()])
def test_readme_sample_matches_real_output(
    command: str, expected: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(REPO)
    main(command.split()[1:])
    actual = capsys.readouterr().out.rstrip("\n").split("\n")
    wanted = expected.rstrip("\n").split("\n")
    assert len(actual) == len(wanted), f"{command}: {len(actual)} lines, README shows {len(wanted)}"
    for want, got in zip(wanted, actual):
        assert line_matches(want, got), f"{command}\nREADME: {want}\nactual: {got}"
