"""Pair type picked on the sign-up form (#33): female_pair, male_pair, mixed_pair."""

from typing import Any

import pytest
from pydantic import ValidationError

from event_ops_engine.capacity import capacity_status
from event_ops_engine.facts import scenario_facts
from event_ops_engine.model import Registration
from tests.conftest import scenario

EVENT = {"at": "2026-11-01T10:00:00+09:00", "status": "confirmed"}


def registration(**fields: Any) -> Registration:
    return Registration.model_validate(
        {"id": "r", "session": "s", "status_events": [EVENT], **fields}
    )


@pytest.mark.parametrize(
    ("pair", "genders"),
    [
        ("female_pair", ["female", "female"]),
        ("male_pair", ["male", "male"]),
        ("mixed_pair", ["female", "male"]),
    ],
)
def test_a_pair_type_alone_expands_to_two_attendees(pair: str, genders: list[str]) -> None:
    reg = registration(pair=pair)
    assert reg.party_size == 2 and not reg.is_unknown_party
    assert [m.gender for m in reg.members or ()] == genders
    assert all(m.birth_year is None for m in reg.members or ())


def test_members_given_with_a_pair_must_match_it_in_any_order() -> None:
    reg = registration(
        pair="mixed_pair", members=[{"gender": "male", "birth_year": 1994}, {"gender": "female"}]
    )
    assert reg.members is not None and reg.members[0].birth_year == 1994
    assert Registration.model_validate(reg.model_dump()) == reg  # a dump loads back unchanged


@pytest.mark.parametrize(
    "fields",
    [
        {"pair": "mixed_pair", "members": [{"gender": "female"}, {"gender": "female"}]},
        {"pair": "female_pair", "members": [{"gender": "female"}, {"gender": "unknown"}]},
        {"pair": "male_pair", "members": [{"gender": "male"}]},
        {"pair": "male_pair", "party_size": 3},
        {"pair": "trio"},
    ],
)
def test_pairs_that_do_not_add_up_are_rejected(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        registration(**fields)


def test_pair_attendees_count_by_gender_and_stay_out_of_age_bands() -> None:
    data = scenario("pair-type")
    (status,) = capacity_status(data)
    counts = {(v.dim, v.value): v.filled for v in status.values}
    assert status.filled == 7
    assert counts[("gender", "female")] == 4  # r1 one, r2 two, r4 one
    assert counts[("gender", "male")] == 3  # r1 one, r3 two
    assert counts[("age_band", "30s")] == 2  # only r3 gave birth years
    rows = scenario_facts(data).rows["given_attr"]
    assert ("r1#2", "gender", "male") in rows and ("r1#2", "age_band", "unknown") in rows
    assert "unknown_party" not in scenario_facts(data).rows  # composition is known
