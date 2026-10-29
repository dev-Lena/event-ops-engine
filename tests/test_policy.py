"""Target resolution: defaults, capacity as default upper bound, per-session overrides."""

from datetime import date

from event_ops_engine.loader import load_policy
from event_ops_engine.model import RatioTarget, Session, TargetRange
from event_ops_engine.policy import resolve_ratios, resolve_targets
from tests.conftest import POLICY


def test_target_hi_defaults_to_session_capacity() -> None:
    policy = load_policy(POLICY)
    rows = resolve_targets(policy, Session(id="s", date=date(2026, 11, 14), capacity=8))
    assert ("age_band", "20s", 2, 8) in rows
    assert ("gender", "female", 6, 6) in rows


def test_session_targets_replace_defaults_for_that_dimension_only() -> None:
    policy = load_policy(POLICY)
    session = Session(
        id="s",
        date=date(2026, 11, 14),
        targets={"gender": {"female": TargetRange(lo=3, hi=4), "male": TargetRange(lo=3, hi=4)}},
    )
    rows = resolve_targets(policy, session)
    assert ("gender", "female", 3, 4) in rows
    assert ("age_band", "30s", 4, 12) in rows


def test_session_ratios_override_defaults() -> None:
    policy = load_policy(POLICY)
    assert resolve_ratios(policy, Session(id="s", date=date(2026, 11, 14))) == [
        ("gender", "female", "male", 1)
    ]
    custom = Session(
        id="s",
        date=date(2026, 11, 14),
        ratios=(RatioTarget(dim="gender", values=("female", "male"), max_diff=0),),
    )
    assert resolve_ratios(policy, custom) == [("gender", "female", "male", 0)]
    assert resolve_ratios(policy, Session(id="s", date=date(2026, 11, 14), ratios=())) == []
