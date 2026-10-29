"""Age band rules: year-level age, inclusive bounds, unknown outside every band."""

from event_ops_engine.bands import age_band, age_in_year, band_for_age
from event_ops_engine.model import AgeBand

BANDS = (
    AgeBand(name="20s", min_age=20, max_age=29),
    AgeBand(name="30s", min_age=30, max_age=39),
    AgeBand(name="40s_plus", min_age=40),
)


def test_age_is_reference_year_minus_birth_year() -> None:
    assert age_in_year(1996, 2026) == 30


def test_band_bounds_are_inclusive_on_both_ends() -> None:
    assert band_for_age(19, BANDS) == "unknown"
    assert band_for_age(20, BANDS) == "20s"
    assert band_for_age(29, BANDS) == "20s"
    assert band_for_age(30, BANDS) == "30s"
    assert band_for_age(39, BANDS) == "30s"
    assert band_for_age(40, BANDS) == "40s_plus"
    assert band_for_age(95, BANDS) == "40s_plus"


def test_missing_birth_year_or_future_birth_year_is_unknown() -> None:
    assert age_band(None, 2026, BANDS) == "unknown"
    assert age_band(2030, 2026, BANDS) == "unknown"


def test_age_band_uses_session_year_as_reference() -> None:
    assert age_band(1997, 2026, BANDS) == "20s"
    assert age_band(1997, 2027, BANDS) == "30s"
