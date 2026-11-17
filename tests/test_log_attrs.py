"""Log attrs reach the rules as the text the author wrote (#102).

YAML 1.1 reads unquoted `true` as a boolean, `014` as octal 12 and `12:30` as 750. The
rules match attrs as text, so each of those used to change a verdict without any error.
"""

import json
import warnings
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType

import pytest

from event_ops_engine.cli import input_warnings_on_stderr, main
from event_ops_engine.decision import VerdictKind
from event_ops_engine.facts import log_facts
from event_ops_engine.harness import run_triage
from event_ops_engine.interpreter import FakeInterpreter
from event_ops_engine.loader import InputWarning, load_scenario, load_triage_scenario
from event_ops_engine.model import LogEvent
from tests.conftest import POLICY, SCENARIOS

TRIAGE = SCENARIOS / "triage"
SEND = "attrs: { channel: sms, result: timeout } }\n"


def write(tmp_path: Path, auto_resend_attrs: str, send_attrs: str = "") -> Path:
    """delivery-timeout.yaml plus a scheduled auto-resend between the send and the receipt."""
    source = (TRIAGE / "delivery-timeout.yaml").read_text(encoding="utf-8")
    assert SEND in source
    resend = (
        "  - { id: e3, at: 2026-11-01T10:01:00+09:00, kind: message_sent, registration: r1,\n"
        f"      attrs: {{ channel: sms, {auto_resend_attrs} }} }}\n"
    )
    sent = SEND.replace("result: timeout", f"result: timeout{send_attrs}")
    path = tmp_path / "scenario.yaml"
    path.write_text(
        source.replace(SEND, sent + resend).replace(
            "policy: ../../../../policy/events/synthetic-example.yaml", f"policy: '{POLICY}'"
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("auto", ['auto: "true"', "auto: true", "auto: True"])
def test_auto_resend_is_recognised_quoted_or_not(tmp_path: Path, auto: str) -> None:
    """The repro: unquoted `auto: true` became "1", the resend counted as manual, and the
    verdict flipped from accept · external_delay to ask."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", InputWarning)
        scenario = load_triage_scenario(write(tmp_path, auto))
    assert ("e3", "auto", "true") in log_facts(scenario).rows["log_attr"]
    verdict = run_triage(scenario, FakeInterpreter())
    assert (verdict.kind, verdict.cause) == (VerdictKind.ACCEPT, "external_delay")


def test_an_adapter_boolean_becomes_text_and_numbers_stay() -> None:
    """A JSON adapter sends `true`, not "true"; it goes through the model, not the YAML loader."""
    event = LogEvent.model_validate_json(
        '{"id": "e1", "at": "2026-11-01T10:00:00+09:00", "kind": "message_sent",'
        ' "attrs": {"auto": true, "manual": false, "digits": 14, "channel": "sms"}}'
    )
    assert event.attrs == {"auto": "true", "manual": "false", "digits": 14, "channel": "sms"}


NUMBER = "a number, not the text typed"


@pytest.mark.parametrize(
    "written, read_as",
    [
        ("014", NUMBER),
        ("12:30", NUMBER),
        ("1_000", NUMBER),
        ("0x1F", NUMBER),
        ("1.0", NUMBER),
        ("+14", NUMBER),
        ("yes", "the boolean true; write true or false"),
        ("Off", "the boolean false; write true or false"),
    ],
)
def test_a_value_yaml_rereads_is_warned_about(tmp_path: Path, written: str, read_as: str) -> None:
    path = write(tmp_path, "auto: true", send_attrs=f", code: {written}")
    with pytest.warns(InputWarning) as caught:
        load_triage_scenario(path)
    (warning,) = caught
    message = str(warning.message)
    assert message.startswith(f"{path}: log event e1, attrs.code: YAML reads this value as ")
    assert read_as in message and message.endswith("The next release refuses it.")


def test_the_warning_never_repeats_the_value(tmp_path: Path) -> None:
    """Log attrs are free text (design.md 3), so neither the typed digits nor the number
    they turn into may reach stderr or a log (design.md 8)."""
    path = write(tmp_path, "auto: true", send_attrs=", code: 01234567")
    with pytest.warns(InputWarning) as caught:
        load_triage_scenario(path)
    told = str(caught[0].message).removeprefix(str(path))
    assert "1234567" not in told and str(0o1234567) not in told


@pytest.mark.parametrize("written", ["14", "-3", "0", '"014"', '"12:30"', "'yes'", "false", "sms"])
def test_a_value_read_as_written_is_not_warned_about(tmp_path: Path, written: str) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", InputWarning)
        load_triage_scenario(write(tmp_path, "auto: true", send_attrs=f", code: {written}"))


def test_a_reread_value_still_loads_as_before_for_one_release(tmp_path: Path) -> None:
    with pytest.warns(InputWarning):
        scenario = load_triage_scenario(write(tmp_path, "auto: true", send_attrs=", code: 014"))
    assert ("e1", "code", "12") in log_facts(scenario).rows["log_attr"]


def test_the_cli_prints_the_warning_on_stderr_and_keeps_stdout_and_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "auto: true", send_attrs=", code: 014")
    assert main(["triage", str(path), "--json"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["matched"] is True
    (line,) = captured.err.splitlines()
    assert line.startswith(f"경고: {path}: log event e1, attrs.code: YAML reads this value as")


def test_other_warnings_keep_their_usual_form(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.warns(UserWarning, match="something else"), input_warnings_on_stderr():
        warnings.warn("something else", UserWarning, stacklevel=1)
    assert "경고:" not in capsys.readouterr().err


def test_a_boolean_in_any_mapping_becomes_text() -> None:
    attrs = MappingProxyType({"auto": True})
    event = LogEvent(id="e1", at=datetime(2026, 11, 1, tzinfo=UTC), kind="k", attrs=attrs)
    assert event.attrs == {"auto": "true"}


FILES = sorted(SCENARIOS.rglob("*.yaml"))


@pytest.mark.parametrize("path", FILES, ids=[p.stem for p in FILES])
def test_no_shipped_scenario_triggers_the_warning(path: Path) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", InputWarning)
        (load_triage_scenario if path.parent == TRIAGE else load_scenario)(path)
