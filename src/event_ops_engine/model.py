"""Layer: lib. Input models (validated with pydantic). No PII fields exist on purpose.

See docs/design.md 3 and docs/glossary.md.
"""

from __future__ import annotations

import datetime as dt
from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

UNKNOWN = "unknown"
"""Reserved attribute value: the attribute is not known (glossary '미상')."""


class Gender(StrEnum):
    FEMALE = "female"
    MALE = "male"
    UNKNOWN = UNKNOWN


class Status(StrEnum):
    """The five registration statuses (glossary '상태 값')."""

    APPLIED = "applied"
    PENDING_PAYMENT = "pending_payment"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Member(StrictModel):
    """One person on a registration: the registrant or a companion."""

    gender: Gender = Gender.UNKNOWN
    birth_year: int | None = Field(default=None, ge=1900, le=2100)


class StatusEvent(StrictModel):
    at: datetime
    status: Status

    @model_validator(mode="after")
    def _require_timezone(self) -> Self:
        if self.at.tzinfo is None:
            raise ValueError("status event time must carry a time zone")
        return self


class Registration(StrictModel):
    """One registration. `members` is None for legacy registrations whose composition is unknown."""

    id: str
    session: str
    party_size: int = Field(ge=1)
    members: tuple[Member, ...] | None = None
    status_events: tuple[StatusEvent, ...] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _default_party_size(cls, data: object) -> object:
        if isinstance(data, dict) and "party_size" not in data and data.get("members"):
            data = {**data, "party_size": len(data["members"])}
        return data

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.members is not None and len(self.members) != self.party_size:
            raise ValueError(f"registration {self.id}: party_size != len(members)")
        times = [event.at for event in self.status_events]
        if len(set(times)) != len(times):
            raise ValueError(f"registration {self.id}: two status events share the same time")
        return self

    @property
    def is_unknown_party(self) -> bool:
        return self.members is None


class AgeBand(StrictModel):
    name: str
    min_age: int = Field(ge=0)
    max_age: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.max_age is not None and self.max_age < self.min_age:
            raise ValueError(f"age band {self.name}: max_age < min_age")
        return self


class AgeBandDimension(StrictModel):
    from_: str = Field(alias="from", default="birth_year")
    bands: tuple[AgeBand, ...] = Field(min_length=1)

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class GenderDimension(StrictModel):
    values: tuple[Gender, ...] = (Gender.FEMALE, Gender.MALE)


class Dimensions(StrictModel):
    gender: GenderDimension = GenderDimension()
    age_band: AgeBandDimension | None = None


class TargetRange(StrictModel):
    """Headcount bounds for one attribute value. `hi` defaults to the session capacity."""

    lo: int = Field(default=0, ge=0)
    hi: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.hi is not None and self.hi < self.lo:
            raise ValueError("target hi < lo")
        return self


class RatioTarget(StrictModel):
    dim: str
    values: tuple[str, str]
    max_diff: int = Field(default=1, ge=0)


Targets = dict[str, dict[str, TargetRange]]
"""dim -> value -> range."""


class SessionDefaults(StrictModel):
    capacity: int = Field(ge=1)
    targets: Targets = Field(default_factory=dict)
    ratios: tuple[RatioTarget, ...] = ()


class PromotionPolicy(StrictModel):
    """Assumed values; the operator's real policy replaces them in policy/events/*.yaml."""

    lead_days: int = Field(ge=0)
    trend_min_per_week: int = Field(ge=0)


class EventPolicy(StrictModel):
    event: str
    dimensions: Dimensions = Dimensions()
    defaults: SessionDefaults
    promotion: PromotionPolicy


class Session(StrictModel):
    id: str
    date: dt.date
    capacity: int | None = Field(default=None, ge=1)
    targets: Targets | None = None
    ratios: tuple[RatioTarget, ...] | None = None


class Scenario(StrictModel):
    policy: EventPolicy
    now: datetime
    sessions: tuple[Session, ...] = Field(min_length=1)
    registrations: tuple[Registration, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.now.tzinfo is None:
            raise ValueError("now must carry a time zone")
        session_ids = {session.id for session in self.sessions}
        if len(session_ids) != len(self.sessions):
            raise ValueError("duplicate session id")
        registration_ids = [registration.id for registration in self.registrations]
        if len(set(registration_ids)) != len(registration_ids):
            raise ValueError("duplicate registration id")
        for registration in self.registrations:
            if registration.session not in session_ids:
                raise ValueError(
                    f"registration {registration.id}: unknown session {registration.session}"
                )
        return self

    def session(self, session_id: str) -> Session:
        for session in self.sessions:
            if session.id == session_id:
                return session
        raise KeyError(session_id)


# --- module ① inquiry triage (docs/design.md 13) -------------------------------------


class LogEvent(StrictModel):
    """One system event (message sent, provider receipt, payment attempt...). Synthetic only."""

    id: str
    at: datetime
    kind: str
    registration: str | None = None
    attrs: dict[str, str | int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _require_timezone(self) -> Self:
        if self.at.tzinfo is None:
            raise ValueError(f"log event {self.id}: time must carry a time zone")
        return self


class Provenance(StrictModel):
    """Where a candidate fact came from: a verbatim quote of the question."""

    source: str = "question"
    quote: str = Field(min_length=1)


class CandidateFact(StrictModel):
    """A fact the interpreter proposes. Validated by the harness before it reaches the rules."""

    relation: str
    args: tuple[str, ...] = Field(min_length=1)
    provenance: Provenance
    confidence: float = Field(ge=0.0, le=1.0)


class Interpretation(StrictModel):
    """The interpreter's whole answer for one question."""

    facts: tuple[CandidateFact, ...] = ()
    note: str = ""


class Question(StrictModel):
    """One synthetic operator inquiry. `canned` is the fake interpreter's answer."""

    id: str
    text: str = Field(min_length=1)
    canned: Interpretation | None = None


class TriageScenario(Scenario):
    """A capacity scenario plus an event log and one question."""

    log: tuple[LogEvent, ...] = ()
    question: Question

    @model_validator(mode="after")
    def _log_consistent(self) -> Self:
        ids = [event.id for event in self.log]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate log event id")
        known = {registration.id for registration in self.registrations}
        for event in self.log:
            if event.registration is not None and event.registration not in known:
                raise ValueError(f"log event {event.id}: unknown registration {event.registration}")
        return self
