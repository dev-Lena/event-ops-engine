"""Layer: lib. The only module that computes ages and age bands.

Domain boundary rules (docs/glossary.md): age = reference year - birth year (year-level
approximation); band bounds are inclusive on both ends; no match or no birth year -> "unknown".
"""

from __future__ import annotations

from collections.abc import Sequence

from .model import UNKNOWN, AgeBand


def age_in_year(birth_year: int, reference_year: int) -> int:
    return reference_year - birth_year


def band_for_age(age: int, bands: Sequence[AgeBand]) -> str:
    for band in bands:
        if age < band.min_age:
            continue
        if band.max_age is not None and age > band.max_age:
            continue
        return band.name
    return UNKNOWN


def age_band(birth_year: int | None, reference_year: int, bands: Sequence[AgeBand]) -> str:
    if birth_year is None:
        return UNKNOWN
    age = age_in_year(birth_year, reference_year)
    if age < 0:
        return UNKNOWN
    return band_for_age(age, bands)
