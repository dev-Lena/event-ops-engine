"""Layer: lib. Input models (validated with pydantic). No PII fields exist on purpose.

See docs/design.md 3 and docs/glossary.md.
"""

from __future__ import annotations

import datetime as dt
from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .decision import VerdictKind

UNKNOWN = "unknown"

TOPICS = ("payment", "delivery", "duplicate", "deadline", "seat")
"""`supported_topic` facts for module ①. A topic is answered only once its type rules exist."""

DEFAULT_TOPIC_ALIASES: dict[str, tuple[str, ...]] = {
    "payment": ("입금", "계좌", "송금", "결제"),
    "delivery": ("문자", "카톡", "알림톡", "안내 메시지", "발송"),
    "duplicate": ("중복", "재신청"),
    "deadline": ("기한", "만료"),
    "seat": ("자리", "정원", "마감", "성비"),
}
"""Approved words that usually mean each topic (assumed; reviewed by PR like any policy)."""
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


class NormalizedValue(StrictModel):
    """A normalizer's answer for one free-text input: the category, how sure, which words.

    `quote` must be part of the input text; the harness rejects anything else.
    """

    value: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    quote: str = Field(min_length=1)


class Member(StrictModel):
    """One person on a registration: the registrant or a companion.

    `job` is the free-text role the person typed (synthetic in this repo, never a name);
    `job_group` is the normalizer's candidate for it, filled by `normalizer.normalize_members`.
    """

    gender: Gender = Gender.UNKNOWN
    birth_year: int | None = Field(default=None, ge=1900, le=2100)
    job: str | None = Field(default=None, min_length=1)
    job_group: NormalizedValue | None = None
    attrs: dict[str, str] = Field(default_factory=dict)
    """Fixed-choice answers for `per: member` choice dimensions (#31), e.g. region."""


class StatusEvent(StrictModel):
    at: datetime
    status: Status

    @model_validator(mode="after")
    def _require_timezone(self) -> Self:
        if self.at.tzinfo is None:
            raise ValueError("status event time must carry a time zone")
        return self


PairType = Literal["female_pair", "male_pair", "mixed_pair"]
PAIR_GENDERS: dict[str, tuple[Gender, Gender]] = {
    "female_pair": (Gender.FEMALE, Gender.FEMALE),
    "male_pair": (Gender.MALE, Gender.MALE),
    "mixed_pair": (Gender.FEMALE, Gender.MALE),
}
"""The genders each pair type fixes (#33). Matches the ops data's headcount rule (design.md 4)."""


class Registration(StrictModel):
    """One registration. `members` is None for legacy registrations whose composition is unknown."""

    id: str
    session: str
    party_size: int = Field(ge=1)
    members: tuple[Member, ...] | None = None
    status_events: tuple[StatusEvent, ...] = Field(min_length=1)
    attrs: dict[str, str] = Field(default_factory=dict)
    """Fixed-choice answers for `per: registration` choice dimensions (#31), e.g. mode."""
    pair: PairType | None = None
    """Pair type picked on the form (#33). Alone it expands to two attendees of those genders
    with unknown birth years; with `members` their genders must match it."""

    @model_validator(mode="before")
    @classmethod
    def _default_party_size(cls, data: object) -> object:
        if isinstance(data, dict) and data.get("pair") in PAIR_GENDERS and not data.get("members"):
            genders = PAIR_GENDERS[data["pair"]]
            data = {**data, "members": [{"gender": gender.value} for gender in genders]}
        if isinstance(data, dict) and "party_size" not in data and data.get("members"):
            data = {**data, "party_size": len(data["members"])}
        return data

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.members is not None and len(self.members) != self.party_size:
            raise ValueError(f"registration {self.id}: party_size != len(members)")
        if self.pair is not None:
            given = sorted(member.gender for member in self.members or ())
            if given != sorted(PAIR_GENDERS[self.pair]):
                raise ValueError(
                    f"registration {self.id}: members do not match pair {self.pair} "
                    f"({', '.join(given) or 'none'})"
                )
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

    @model_validator(mode="after")
    def _no_unknown(self) -> Self:
        if Gender.UNKNOWN in self.values:
            raise ValueError(f"gender values must not include {UNKNOWN!r} (reserved)")
        return self


class JobGroupDimension(StrictModel):
    """Free-text job → one of `values`, proposed by an LLM normalizer (docs/design.md 14)."""

    values: tuple[str, ...] = Field(min_length=1)
    normalize: Literal["llm"] = "llm"
    min_confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    """Assumed value: a candidate below it is counted as unknown and sent to needs_review."""
    aliases: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    """Approved dictionary (#62): value -> words that mean it. One clear hit settles a job
    text without the LLM; no hit or hits for several values go to the normalizer. A word may
    appear under one value only, or it could never settle anything."""

    @model_validator(mode="after")
    def _values_distinct_and_not_unknown(self) -> Self:
        if len(set(self.values)) != len(self.values):
            raise ValueError("job_group values must be distinct")
        if UNKNOWN in self.values:
            raise ValueError(f"job_group values must not include {UNKNOWN!r}")
        unknown = sorted(set(self.aliases) - set(self.values))
        if unknown:
            raise ValueError(f"job_group aliases name unknown values {unknown}")
        words = [word.strip().lower() for listed in self.aliases.values() for word in listed]
        if any(not word for word in words):
            raise ValueError("job_group aliases must not be blank")
        repeated = sorted({word for word in words if words.count(word) > 1})
        if repeated:
            raise ValueError(f"job_group aliases list a word more than once: {repeated}")
        return self


class ChoiceDimension(StrictModel):
    """A fixed-choice attribute picked on the sign-up form (#31), e.g. region or participation
    mode. The answer is taken as given; nothing is normalized."""

    values: tuple[str, ...] = Field(min_length=1)
    per: Literal["member", "registration"] = "member"
    """`registration`: one answer for everyone on the registration (a pair joins the same way)."""

    @model_validator(mode="after")
    def _values_distinct_and_not_unknown(self) -> Self:
        if len(set(self.values)) != len(self.values):
            raise ValueError("choice values must be distinct")
        if UNKNOWN in self.values or any(not value for value in self.values):
            raise ValueError(f"choice values must be non-empty and not {UNKNOWN!r}")
        return self


DIM_GENDER = "gender"
DIM_AGE_BAND = "age_band"
DIM_JOB_GROUP = "job_group"
BUILTIN_DIMENSIONS = (DIM_GENDER, DIM_AGE_BAND, DIM_JOB_GROUP)


class Dimensions(StrictModel):
    gender: GenderDimension = GenderDimension()
    age_band: AgeBandDimension | None = None
    job_group: JobGroupDimension | None = None
    choices: dict[str, ChoiceDimension] = Field(default_factory=dict)
    """Fixed-choice attributes by name (#31). Counted like any other dimension by the rules."""

    @model_validator(mode="after")
    def _choice_names(self) -> Self:
        clash = sorted(set(self.choices) & set(BUILTIN_DIMENSIONS))
        if clash or any(not name for name in self.choices):
            raise ValueError(f"choice names must be non-empty and not built in: {clash}")
        return self

    def value_pairs(self) -> tuple[tuple[str, str], ...]:
        """Every declared (dim, value): what targets, ratios and questions may name."""
        pairs = [(DIM_GENDER, gender.value) for gender in self.gender.values]
        if self.age_band is not None:
            pairs += [(DIM_AGE_BAND, band.name) for band in self.age_band.bands]
        if self.job_group is not None:
            pairs += [(DIM_JOB_GROUP, value) for value in self.job_group.values]
        for name, choice in self.choices.items():
            pairs += [(name, value) for value in choice.values]
        return tuple(pairs)

    def check_targets(self, targets: Targets, ratios: tuple[RatioTarget, ...], where: str) -> None:
        """Reject targets or ratios on an undeclared dim or value: they could never be met."""
        declared = set(self.value_pairs())
        named = [(dim, value) for dim, by_value in targets.items() for value in by_value]
        named += [(ratio.dim, value) for ratio in ratios for value in ratio.values]
        unknown = sorted({pair for pair in named if pair not in declared})
        if unknown:
            raise ValueError(f"{where}: targets name undeclared attribute values {unknown}")


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
    """Promotion thresholds (docs/design.md 7). Which are confirmed and which assumed is marked
    there and in policy/events/*.yaml."""

    lead_days: int = Field(ge=0)
    trend_min_per_week: int = Field(ge=0)
    promotion_cutoff_hours: int = Field(default=2, ge=0)
    """Confirmed (#52): promotion recommendations stop this many hours before a session starts."""


class TriagePolicy(StrictModel):
    """Assumed values for module ① type rules (docs/design.md 13)."""

    grace_minutes: int = Field(default=0, ge=0)
    """A payment attempt this long after the due time still counts as on time. The bank
    blocks the account at the due time itself, so the default is 0."""
    payment_deadline_hours: int = Field(default=24, ge=1)
    """Hours after selection (pending_payment) a registration may pay. Sessions override it."""
    sync_lag_minutes: int = Field(default=10, ge=0)
    """Assumed value: a provider-confirmed payment may stay pending this long before it is a
    suspected bug (the real system polled every 10 minutes, now real time)."""
    min_candidate_confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    """Assumed value: interpreter candidates below it never reach the rules (#59)."""
    topic_aliases: dict[str, tuple[str, ...]] = Field(
        default_factory=lambda: dict(DEFAULT_TOPIC_ALIASES)
    )
    """Approved dictionary handed to the interpreter (#62): topic -> words that mean it."""

    @model_validator(mode="after")
    def _aliases_name_known_topics(self) -> Self:
        unknown = sorted(set(self.topic_aliases) - set(TOPICS))
        if unknown:
            raise ValueError(f"topic_aliases: unknown topics {unknown}")
        return self


class EventPolicy(StrictModel):
    event: str
    dimensions: Dimensions = Dimensions()
    defaults: SessionDefaults
    promotion: PromotionPolicy
    triage: TriagePolicy = TriagePolicy()

    @model_validator(mode="after")
    def _targets_declared(self) -> Self:
        self.dimensions.check_targets(self.defaults.targets, self.defaults.ratios, "defaults")
        return self


class Session(StrictModel):
    id: str
    date: dt.date
    capacity: int | None = Field(default=None, ge=1)
    targets: Targets | None = None
    ratios: tuple[RatioTarget, ...] | None = None
    payment_deadline_hours: int | None = Field(default=None, ge=1)
    start_time: dt.time | None = None
    """Asia/Seoul wall-clock start. Without it promotion is judged by date only (design.md 7)."""
    lead_days: int | None = Field(default=None, ge=0)
    promotion_cutoff_hours: int | None = Field(default=None, ge=0)

    @field_validator("start_time", mode="before")
    @classmethod
    def _start_time_is_text(cls, value: object) -> object:
        # YAML 1.1 reads an unquoted 19:30 as the integer 1170, which pydantic would
        # silently turn into 00:19:30. Only quoted "HH:MM" text is accepted.
        if value is not None and not isinstance(value, (str, dt.time)):
            raise ValueError('start_time must be quoted text such as "19:30"')
        return value

    @field_validator("start_time")
    @classmethod
    def _start_time_is_local(cls, value: dt.time | None) -> dt.time | None:
        if value is not None and value.tzinfo is not None:
            raise ValueError("start_time is Asia/Seoul local time; drop the offset")
        return value


class Scenario(StrictModel):
    policy: EventPolicy
    now: datetime
    sessions: tuple[Session, ...] = Field(min_length=1)
    registrations: tuple[Registration, ...] = ()
    canned_job_groups: dict[str, NormalizedValue] = Field(default_factory=dict)
    """Fake normalizer answers keyed by the member's `job` text. Synthetic scenarios only."""

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
        dimensions = self.policy.dimensions
        for session in self.sessions:
            dimensions.check_targets(
                session.targets or {}, session.ratios or (), f"session {session.id}"
            )
        for registration in self.registrations:
            answers = [("registration", registration.attrs)]
            answers += [("member", member.attrs) for member in registration.members or ()]
            for level, attrs in answers:
                for name, value in attrs.items():
                    choice = dimensions.choices.get(name)
                    if choice is None or choice.per != level:
                        raise ValueError(
                            f"registration {registration.id}: {name!r} is not a "
                            f"per-{level} choice attribute in the policy"
                        )
                    if value not in choice.values:
                        raise ValueError(
                            f"registration {registration.id}: {name}={value!r} is not one of "
                            f"{list(choice.values)}"
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

    def __hash__(self) -> int:  # frozen model with a dict field: hash by identity fields
        return hash((self.id, self.at, self.kind))

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


class ExpectedVerdict(StrictModel):
    """What the scenario author expects. `event-ops triage` reports any difference.

    `cause` and `needs` left as None are not compared; `needs: []` means "nothing missing".
    """

    kind: VerdictKind
    cause: str | None = None
    needs: tuple[str, ...] | None = None


class TriageScenario(Scenario):
    """A capacity scenario plus an event log, one question and the expected verdict."""

    log: tuple[LogEvent, ...] = ()
    question: Question
    expected: ExpectedVerdict | None = None

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
