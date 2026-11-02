"""Normalizers: the fake answers from a table, the CLI one parses JSON, members get filled."""

from collections.abc import Sequence

import pytest
from pydantic import ValidationError

from event_ops_engine.loader import load_scenario
from event_ops_engine.model import (
    UNKNOWN,
    EventPolicy,
    JobGroupDimension,
    Member,
    NormalizedValue,
)
from event_ops_engine.normalizer import (
    ClaudeCliNormalizer,
    FakeNormalizer,
    NormalizationError,
    NormalizeContext,
    build_normalize_prompt,
    normalize_member,
    normalize_members,
    parse_normalized,
)
from tests.conftest import SCENARIOS

JOB_GROUP = SCENARIOS / "job-group.yaml"
CONTEXT = NormalizeContext("job_group", ("engineering", "design", "product", "other"))


def test_fake_answers_from_the_scenario_table_or_fails_loudly() -> None:
    scenario = load_scenario(JOB_GROUP)
    fake = FakeNormalizer.from_scenario(scenario)
    assert fake.normalize("백엔드 3년차", CONTEXT).value == "engineering"
    with pytest.raises(NormalizationError):
        fake.normalize("없는 문구", CONTEXT)


def test_normalize_members_fills_job_group_and_leaves_the_rest_alone() -> None:
    scenario = load_scenario(JOB_GROUP)
    done = normalize_members(scenario, FakeNormalizer.from_scenario(scenario))
    by_id = {r.id: r for r in done.registrations}
    assert by_id["r1"].members is not None and by_id["r1"].members[0].job_group is not None
    assert by_id["r1"].members[0].job_group.value == "engineering"
    assert by_id["r5"].members is not None and by_id["r5"].members[0].job_group is None
    assert normalize_members(done, FakeNormalizer({})) == done  # already resolved: untouched


def test_missing_or_unquotable_answers_become_unknown_with_zero_confidence() -> None:
    member = Member(job="프론트엔드")
    assert normalize_member(member, FakeNormalizer({}), CONTEXT).job_group == NormalizedValue(
        value=UNKNOWN, confidence=0.0, quote="프론트엔드"
    )
    invented = FakeNormalizer(
        {"프론트엔드": NormalizedValue(value="engineering", confidence=0.9, quote="백엔드")}
    )
    resolved = normalize_member(member, invented, CONTEXT).job_group
    assert resolved is not None and resolved.value == UNKNOWN and resolved.confidence == 0.0


def test_scenario_without_job_group_dimension_is_returned_as_is() -> None:
    scenario = load_scenario(SCENARIOS / "single.yaml")
    assert normalize_members(scenario, FakeNormalizer({})) is scenario


def test_cli_normalizer_parses_json_and_prompts_with_allowed_values() -> None:
    seen: dict[str, object] = {}

    def fake_run(command: Sequence[str], stdin: str) -> str:
        seen["stdin"] = stdin
        return 'Sure: {"value": "design", "confidence": 0.8, "quote": "디자이너"}'

    result = ClaudeCliNormalizer(run=fake_run).normalize("디자이너 5년", CONTEXT)
    assert (result.value, result.confidence, result.quote) == ("design", 0.8, "디자이너")
    prompt = str(seen["stdin"])
    assert "engineering, design, product, other" in prompt and "디자이너 5년" in prompt


@pytest.mark.parametrize(
    "raw", ["nope", '{"value": "x"}', '{"value": "x", "confidence": 2, "quote": "x"}']
)
def test_unusable_normalizer_output_is_an_error(raw: str) -> None:
    with pytest.raises(NormalizationError):
        parse_normalized(raw)


def test_prompt_mentions_low_confidence_for_vague_text() -> None:
    assert "low value" in build_normalize_prompt("뭐든 합니다", CONTEXT)


def test_job_group_dimension_schema() -> None:
    assert JobGroupDimension(values=("a", "b")).min_confidence == 0.7
    with pytest.raises(ValidationError):
        JobGroupDimension(values=())
    with pytest.raises(ValidationError):
        JobGroupDimension(values=("a", "a"))
    with pytest.raises(ValidationError):
        JobGroupDimension(values=("a", UNKNOWN))
    with pytest.raises(ValidationError):
        JobGroupDimension(values=("a",), min_confidence=1.5)
    with pytest.raises(ValidationError):
        JobGroupDimension.model_validate({"values": ["a"], "normalize": "regex"})
    policy = load_scenario(JOB_GROUP).policy
    assert isinstance(policy, EventPolicy) and policy.dimensions.job_group is not None
