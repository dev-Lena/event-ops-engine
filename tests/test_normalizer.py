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
    assert fake.normalize("마케팅 겸 기획 하고 있어요", CONTEXT).value == "product"
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


def test_cli_normalizer_sends_all_texts_in_one_prompt() -> None:
    calls: list[str] = []

    def fake_run(command: Sequence[str], stdin: str) -> str:
        calls.append(stdin)
        return (
            'Sure: {"answers": [{"index": 1, "value": "design", "confidence": 0.8, '
            '"quote": "디자이너"}, {"index": 2, "value": "product", "confidence": 0.7, '
            '"quote": "PO"}]}'
        )

    answers = ClaudeCliNormalizer(run=fake_run).normalize_batch(["디자이너 5년", "PO 2년"], CONTEXT)
    assert len(calls) == 1 and "1. 디자이너 5년" in calls[0] and "2. PO 2년" in calls[0]
    assert "engineering, design, product, other" in calls[0]
    assert answers["디자이너 5년"].value == "design" and answers["PO 2년"].quote == "PO"


@pytest.mark.parametrize(
    "raw",
    ["nope", '{"value": "x"}', '{"answers": "x"}'],
)
def test_unusable_normalizer_output_is_an_error(raw: str) -> None:
    with pytest.raises(NormalizationError):
        parse_normalized(raw, ["a"])


def test_malformed_answers_are_skipped_not_fatal() -> None:
    raw = (
        '{"answers": [{"index": 1, "value": "x", "confidence": 2, "quote": "a"},'
        ' {"index": 9, "value": "x", "confidence": 0.5, "quote": "b"},'
        ' "junk", {"index": 2, "value": "design", "confidence": 0.9, "quote": "b"}]}'
    )
    assert list(parse_normalized(raw, ["a", "b"])) == ["b"]


def test_prompt_mentions_low_confidence_for_vague_text() -> None:
    assert "low value" in build_normalize_prompt(["뭐든 합니다"], CONTEXT)


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


# --- approved alias dictionary and fewer calls (#62 · #63) ---------------------------------

ALIASED = NormalizeContext(
    "job_group",
    ("engineering", "design", "product", "other"),
    (("engineering", ("백엔드", "개발자")), ("product", ("기획",)), ("other", ("마케팅",))),
)


class CountingFake(FakeNormalizer):
    def __init__(self, canned: dict[str, NormalizedValue]) -> None:
        super().__init__(canned)
        self.asked: list[str] = []

    def normalize(self, text: str, context: NormalizeContext) -> NormalizedValue:
        self.asked.append(text)
        return super().normalize(text, context)


def test_one_clear_alias_hit_settles_without_the_normalizer() -> None:
    from event_ops_engine.normalizer import match_alias

    hit = match_alias("Backend 백엔드 3년차", ALIASED)
    assert hit == NormalizedValue(value="engineering", confidence=1.0, quote="백엔드")
    assert match_alias("Design lead", ALIASED) == NormalizedValue(
        value="design", confidence=1.0, quote="Design"
    )  # the value's own name counts, quoted as written


def test_no_hit_or_hits_for_several_values_go_to_the_normalizer() -> None:
    from event_ops_engine.normalizer import match_alias

    assert match_alias("대학원생", ALIASED) is None
    assert match_alias("마케팅 겸 기획", ALIASED) is None


def test_each_distinct_text_is_asked_once_and_aliases_skip_the_call() -> None:
    from event_ops_engine.normalizer import resolve_texts

    fake = CountingFake(
        {"대학원생": NormalizedValue(value="other", confidence=0.8, quote="대학원생")}
    )
    answers = resolve_texts(["백엔드 3년차", "대학원생", "대학원생", "백엔드 3년차"], fake, ALIASED)
    assert fake.asked == ["대학원생"]
    assert answers["백엔드 3년차"].confidence == 1.0 and answers["대학원생"].value == "other"


def test_batch_normalizer_gets_one_call_for_all_remaining_texts() -> None:
    from event_ops_engine.normalizer import resolve_texts

    calls: list[str] = []

    def fake_run(command: Sequence[str], stdin: str) -> str:
        calls.append(stdin)
        return '{"answers": [{"index": 1, "value": "other", "confidence": 0.9, "quote": "학생"}]}'

    answers = resolve_texts(
        ["학생", "무직", "학생", "개발자"], ClaudeCliNormalizer(run=fake_run), ALIASED
    )
    assert len(calls) == 1 and "1. 학생" in calls[0] and "2. 무직" in calls[0]
    assert "개발자" not in calls[0].split("Texts:")[1]  # settled by the dictionary
    assert answers["무직"].value == UNKNOWN and answers["학생"].value == "other"
    assert "engineering: 백엔드, 개발자" in calls[0]


def test_batch_failure_leaves_remaining_texts_unknown() -> None:
    from event_ops_engine.interpreter import InterpretationError
    from event_ops_engine.normalizer import resolve_texts

    def logged_out(command: Sequence[str], stdin: str) -> str:
        raise InterpretationError("not logged in")

    answers = resolve_texts(["백엔드", "학생"], ClaudeCliNormalizer(run=logged_out), ALIASED)
    assert answers["백엔드"].value == "engineering" and answers["학생"].value == UNKNOWN


def test_scenario_aliases_keep_settled_texts_away_from_the_fake() -> None:
    scenario = load_scenario(JOB_GROUP)
    fake = CountingFake(dict(scenario.canned_job_groups))
    normalize_members(scenario, fake)
    assert sorted(fake.asked) == ["대학원생", "마케팅 겸 기획 하고 있어요"]


def test_alias_dictionary_is_validated() -> None:
    from event_ops_engine.model import TriagePolicy

    with pytest.raises(ValidationError):
        JobGroupDimension(values=("a",), aliases={"b": ("x",)})
    with pytest.raises(ValidationError):
        JobGroupDimension(values=("a",), aliases={"a": (" ",)})
    with pytest.raises(ValidationError):
        TriagePolicy(topic_aliases={"weather": ("비",)})
    assert "delivery" in TriagePolicy().topic_aliases
