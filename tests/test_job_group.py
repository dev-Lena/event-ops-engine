"""job_group end to end: candidates above the threshold count, the rest are unknown + review."""

from event_ops_engine.capacity import capacity_status
from event_ops_engine.engine import Engine
from event_ops_engine.facts import Facts, scenario_facts
from event_ops_engine.loader import load_scenario
from event_ops_engine.model import JobGroupDimension, Scenario
from event_ops_engine.normalizer import FakeNormalizer, normalize_members
from tests.conftest import SCENARIOS


def rows_of(facts: Facts, relation: str) -> list[tuple[object, ...]]:
    return facts.rows.get(relation, [])


def normalized(min_confidence: float | None = None) -> Scenario:
    scenario = load_scenario(SCENARIOS / "job-group.yaml")
    if min_confidence is not None:
        dims = scenario.policy.dimensions
        job_group = dims.job_group
        assert job_group is not None
        policy = scenario.policy.model_copy(
            update={
                "dimensions": dims.model_copy(
                    update={
                        "job_group": job_group.model_copy(update={"min_confidence": min_confidence})
                    }
                )
            }
        )
        scenario = scenario.model_copy(update={"policy": policy})
    return normalize_members(scenario, FakeNormalizer.from_scenario(scenario))


def test_candidate_facts_carry_percent_confidence_and_evidence() -> None:
    facts = scenario_facts(normalized())
    candidates = {row[0]: row[1:] for row in rows_of(facts, "candidate_attr")}
    assert candidates["r1#1"] == ("job_group", "engineering", 95, "job/r1#1")
    assert candidates["r3#1"] == ("job_group", "product", 55, "job/r3#1")
    assert ("r5#1", "job_group", "unknown") in rows_of(facts, "given_attr")
    assert ("job_group", 70) in rows_of(facts, "normalize_threshold")
    assert ("job_group", "other") in rows_of(facts, "dimension_value")


def test_each_attendee_gets_exactly_one_job_group(engine: Engine) -> None:
    engine.load(scenario_facts(normalized()))
    attrs = [(a, v) for a, d, v in engine.snapshot("attendee_attr") if d == "job_group"]
    assert sorted(attrs) == [
        ("r1#1", "engineering"),
        ("r2#1", "design"),
        ("r3#1", "unknown"),
        ("r4#1", "unknown"),
        ("r5#1", "unknown"),
    ]


def test_status_counts_promoted_candidates_and_flags_the_rest() -> None:
    (status,) = capacity_status(normalized())
    by_value = {(v.dim, v.value): v for v in status.values}
    assert by_value[("job_group", "engineering")].filled == 1
    assert by_value[("job_group", "design")].filled == 1
    reviews = {d.evidence[0]: d.reasons for d in status.needs_review}
    assert reviews == {
        "registration/r3": ("low_confidence",),
        "registration/r4": ("unknown_value",),
    }
    assert any("job/r3#1" in d.evidence for d in status.needs_review)


def test_threshold_comes_from_the_policy() -> None:
    (status,) = capacity_status(normalized(min_confidence=0.96))
    by_value = {(v.dim, v.value): v for v in status.values}
    assert by_value[("job_group", "engineering")].filled == 0
    assert {d.evidence[0] for d in status.needs_review} == {
        "registration/r1",
        "registration/r2",
        "registration/r3",
        "registration/r4",
    }


def test_unnormalized_scenario_counts_everyone_as_unknown() -> None:
    (status,) = capacity_status(load_scenario(SCENARIOS / "job-group.yaml"))
    assert all(v.filled == 0 for v in status.values if v.dim == "job_group")
    assert status.needs_review == ()


def test_dimension_values_include_job_groups() -> None:
    from event_ops_engine.facts import dimension_values

    assert ("job_group", "design") in dimension_values(normalized().policy)
    assert JobGroupDimension(values=("x",)).normalize == "llm"


def test_threshold_boundary_is_at_one_percent_resolution_rounded_down() -> None:
    from event_ops_engine.facts import confidence_pct

    assert confidence_pct(0.7) == 70 and confidence_pct(0.695) == 69
    assert confidence_pct(0.29) == 29 and confidence_pct(1.0) == 100


def test_two_member_registration_reviews_once_and_cites_only_rejected_candidates() -> None:
    from event_ops_engine.model import Member, NormalizedValue

    scenario = load_scenario(SCENARIOS / "job-group.yaml")
    r3 = next(r for r in scenario.registrations if r.id == "r3")
    assert r3.members is not None
    pair = r3.model_copy(
        update={"members": (r3.members[0], Member(job="백엔드 3년차")), "party_size": 2}
    )
    scenario = scenario.model_copy(
        update={"registrations": tuple(pair if r.id == "r3" else r for r in scenario.registrations)}
    )
    (status,) = capacity_status(normalize_members(scenario, FakeNormalizer.from_scenario(scenario)))
    reviews = [d for d in status.needs_review if d.evidence[0] == "registration/r3"]
    assert len(reviews) == 1 and reviews[0].reasons == ("low_confidence",)
    assert reviews[0].evidence == ("registration/r3", "job/r3#1")  # r3#2 passed
    assert isinstance(NormalizedValue, type)
