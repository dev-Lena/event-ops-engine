"""Input validation: the model rejects inconsistent registrations and naive times."""

from datetime import date

import pytest
from pydantic import ValidationError

from event_ops_engine.model import Registration, Scenario
from tests.conftest import POLICY, scenario

from event_ops_engine.loader import load_policy  # isort: skip

EVENT = {"at": "2026-10-20T10:00:00+09:00", "status": "confirmed"}


def test_party_size_defaults_to_member_count() -> None:
    reg = Registration.model_validate(
        {"id": "r", "session": "s", "members": [{}, {}], "status_events": [EVENT]}
    )
    assert reg.party_size == 2
    assert not reg.is_unknown_party


def test_party_size_must_match_members() -> None:
    with pytest.raises(ValidationError, match="party_size"):
        Registration.model_validate(
            {"id": "r", "session": "s", "party_size": 3, "members": [{}], "status_events": [EVENT]}
        )


def test_registration_without_members_is_unknown_party() -> None:
    reg = Registration.model_validate(
        {"id": "r", "session": "s", "party_size": 2, "status_events": [EVENT]}
    )
    assert reg.is_unknown_party


def test_two_status_events_at_the_same_time_are_rejected() -> None:
    with pytest.raises(ValidationError, match="same time"):
        Registration.model_validate(
            {"id": "r", "session": "s", "members": [{}], "status_events": [EVENT, EVENT]}
        )


def test_unknown_status_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Registration.model_validate(
            {
                "id": "r",
                "session": "s",
                "members": [{}],
                "status_events": [{"at": EVENT["at"], "status": "approved"}],
            }
        )


def test_naive_status_time_is_rejected() -> None:
    with pytest.raises(ValidationError, match="time zone"):
        Registration.model_validate(
            {
                "id": "r",
                "session": "s",
                "members": [{}],
                "status_events": [{"at": "2026-10-20T10:00:00", "status": "confirmed"}],
            }
        )


def test_registration_must_point_at_a_known_session() -> None:
    policy = load_policy(POLICY)
    with pytest.raises(ValidationError, match="unknown session"):
        Scenario(
            policy=policy,
            now=scenario("single").now,
            sessions=({"id": "s1", "date": date(2026, 11, 21)},),  # type: ignore[arg-type]
            registrations=(
                Registration.model_validate(
                    {"id": "r", "session": "nope", "members": [{}], "status_events": [EVENT]}
                ),
            ),
        )


def test_model_has_no_personal_identifier_fields() -> None:
    from event_ops_engine.model import Member

    # `job` is a free-text role ("백엔드 3년차"), never a name or contact; `job_group` is the
    # normalizer's candidate for it. `attrs` holds only answers from a declared choice attribute's
    # fixed list (#31; free text is rejected, see tests/test_choices.py).
    assert set(Member.model_fields) == {"gender", "birth_year", "job", "job_group", "attrs"}
    assert set(Registration.model_fields) == {
        "id",
        "session",
        "party_size",
        "members",
        "status_events",
        "attrs",
    }
