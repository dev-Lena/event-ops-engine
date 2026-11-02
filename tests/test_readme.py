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
    """`...` in a README line elides a middle part; the text before and after must match."""
    head, ellipsis, tail = expected.partition("...")
    if not ellipsis:
        return actual == expected
    return actual.startswith(head) and actual.endswith(tail) and len(actual) >= len(head + tail)


def test_every_readme_command_block_is_a_sample() -> None:
    """A block the regex cannot pair with its output must fail, not silently drop out."""
    text = README.read_text(encoding="utf-8")
    commands = [command for command, _ in samples()]
    assert len(commands) == text.count("```bash\nevent-ops ")
    assert any(c.startswith("event-ops report ") for c in commands)
    assert any(c.startswith("event-ops triage ") for c in commands)


@pytest.mark.parametrize("command, expected", samples(), ids=[c for c, _ in samples()])
def test_readme_sample_matches_real_output(
    command: str, expected: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(REPO)
    assert main(command.split()[1:]) == 0
    actual = capsys.readouterr().out.rstrip("\n").split("\n")
    wanted = expected.rstrip("\n").split("\n")
    assert len(actual) == len(wanted), f"{command}: {len(actual)} lines, README shows {len(wanted)}"
    for want, got in zip(wanted, actual):
        assert line_matches(want, got), f"{command}\nREADME: {want}\nactual: {got}"
