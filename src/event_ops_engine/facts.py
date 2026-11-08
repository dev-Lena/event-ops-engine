"""Layer: lib. Turns a validated Scenario into engine facts and evidence ids.

Headcount conversion (docs/design.md 4): one registration becomes `party_size` attendees.
Registrations with unknown composition get attendees whose attributes are all "unknown".
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from . import bands, clock
from .model import (
    DIM_AGE_BAND,
    DIM_GENDER,
    DIM_JOB_GROUP,
    TOPICS,
    UNKNOWN,
    CandidateFact,
    EventPolicy,
    Member,
    Question,
    Registration,
    Scenario,
    Session,
    TriageScenario,
)
from .policy import resolve_promotion, resolve_ratios, resolve_targets

Row = tuple[Any, ...]


def confidence_pct(confidence: float) -> int:
    """Rules compare integers at 1% resolution: 0.0~1.0 becomes 0~100, rounded **down**.

    Rounding down on both sides keeps `candidate >= threshold` true only when the real
    values satisfy it (0.695 must not pass 0.7). The epsilon absorbs float error (0.29*100).
    """
    return int(math.floor(confidence * 100 + 1e-9))


def squash(text: str) -> str:
    """Collapse runs of whitespace so a quote is still 'verbatim' across line breaks."""
    return " ".join(text.split())


@dataclass
class Facts:
    """Rows per relation, in insertion order, plus the evidence id of every input fact."""

    rows: dict[str, list[Row]] = field(default_factory=lambda: defaultdict(list))

    def add(self, relation: str, *row: Any) -> None:
        self.rows[relation].append(tuple(row))

    def extend(self, other: Facts) -> None:
        for relation, rows in other.rows.items():
            self.rows[relation].extend(rows)

    def relations(self) -> list[str]:
        return list(self.rows)


def attendee_id(registration_id: str, index: int) -> str:
    return f"{registration_id}#{index + 1}"


def evidence_id(relation: str, *key: Any) -> str:
    return "/".join([relation, *(str(part) for part in key)])


def session_facts(scenario: Scenario, session: Session) -> Facts:
    facts = Facts()
    policy = scenario.policy
    capacity = session.capacity or policy.defaults.capacity
    facts.add("session_capacity", session.id, capacity)
    facts.add("days_left", session.id, clock.days_left(scenario.now, session.date))
    for dim, value, lo, hi in resolve_targets(policy, session):
        facts.add("target", session.id, dim, value, lo, hi)
    for dim, value_a, value_b, max_diff in resolve_ratios(policy, session):
        facts.add("ratio_target", session.id, dim, value_a, value_b, max_diff)
    promotion = resolve_promotion(policy, session)
    for key, n in promotion.items():
        facts.add("policy", session.id, key, n)
    cutoff_hours = promotion["promotion_cutoff_hours"]
    if session.start_time is not None:
        cutoff = clock.promotion_cutoff(session.date, session.start_time, cutoff_hours)
        facts.add("promotion_cutoff_ts", session.id, clock.to_epoch(cutoff))
    else:
        earliest = clock.earliest_promotion_cutoff(session.date, cutoff_hours)
        facts.add("earliest_cutoff_ts", session.id, clock.to_epoch(earliest))
    hours = session.payment_deadline_hours or policy.triage.payment_deadline_hours
    facts.add("deadline_hours", session.id, hours)
    return facts


def choice_attributes(
    member: Member | None, registration: Registration, scenario: Scenario
) -> list[Row]:
    """(dim, value) for every choice dimension (#31): the registration's or the member's
    answer by the dimension's `per`, `unknown` when it was not given."""
    pairs: list[Row] = []
    for name, choice in scenario.policy.dimensions.choices.items():
        if choice.per == "registration":
            source = registration.attrs
        else:
            source = member.attrs if member is not None else {}
        pairs.append((name, source.get(name, UNKNOWN)))
    return pairs


def member_attributes(member: Member | None, scenario: Scenario, session: Session) -> list[Row]:
    """`given_attr` (dim, value) pairs for one attendee; `member is None` means unknown composition.

    A job_group comes from the normalizer as a `candidate_attr` instead (see
    `registration_facts`); here it is only `unknown` when there is no candidate. Choice
    dimensions come from `choice_attributes`.
    """
    dimensions = scenario.policy.dimensions
    if member is None:
        pairs: list[Row] = [(DIM_GENDER, UNKNOWN)]
        if dimensions.age_band is not None:
            pairs.append((DIM_AGE_BAND, UNKNOWN))
        if dimensions.job_group is not None:
            pairs.append((DIM_JOB_GROUP, UNKNOWN))
        return pairs
    pairs = [(DIM_GENDER, member.gender.value)]
    if dimensions.age_band is not None:
        band = bands.age_band(member.birth_year, session.date.year, dimensions.age_band.bands)
        pairs.append((DIM_AGE_BAND, band))
    if dimensions.job_group is not None and member.job_group is None:
        pairs.append((DIM_JOB_GROUP, UNKNOWN))
    return pairs


def registration_facts(scenario: Scenario, registration: Registration) -> Facts:
    facts = Facts()
    session = scenario.session(registration.session)
    facts.add("registration", registration.id, registration.session)
    members: list[Member | None] = (
        list(registration.members)
        if registration.members is not None
        else [None] * registration.party_size
    )
    if registration.is_unknown_party:
        facts.add("unknown_party", registration.id, registration.party_size)
    for index, member in enumerate(members):
        attendee = attendee_id(registration.id, index)
        facts.add("attendee", registration.id, attendee)
        for dim, value in member_attributes(member, scenario, session) + choice_attributes(
            member, registration, scenario
        ):
            facts.add("given_attr", attendee, dim, value)
        if member is not None and member.job_group is not None:
            candidate = member.job_group
            facts.add(
                "candidate_attr",
                attendee,
                DIM_JOB_GROUP,
                candidate.value,
                confidence_pct(candidate.confidence),
                evidence_id("job", attendee),
            )
    for event in registration.status_events:
        facts.add("status_event", registration.id, clock.to_epoch(event.at), event.status.value)
    return facts


def normalization_facts(scenario: Scenario) -> Facts:
    """Threshold and allowed values the rules use to promote `candidate_attr` rows."""
    facts = Facts()
    job_group = scenario.policy.dimensions.job_group
    if job_group is not None:
        facts.add("normalize_threshold", DIM_JOB_GROUP, confidence_pct(job_group.min_confidence))
        for value in job_group.values:
            facts.add("dimension_value", DIM_JOB_GROUP, value)
    return facts


def scenario_facts(scenario: Scenario) -> Facts:
    """Facts for a scenario whose job texts are already normalized (`normalize_members`)."""
    facts = Facts()
    facts.add("now", clock.to_epoch(scenario.now))
    facts.extend(normalization_facts(scenario))
    for session in scenario.sessions:
        facts.extend(session_facts(scenario, session))
    for registration in scenario.registrations:
        facts.extend(registration_facts(scenario, registration))
    return facts


# --- module ① inquiry triage (docs/design.md 13) -------------------------------------


CANDIDATE_RELATIONS: dict[str, tuple[str, ...]] = {
    "asks_about": ("topic",),
    "about_registration": ("registration",),
    "about_session": ("session",),
    "about_event": ("log",),
    "about_value": ("dim", "value"),
}
"""Relations the interpreter may propose, and what each argument must name."""


def dimension_values(policy: EventPolicy) -> tuple[tuple[str, str], ...]:
    """Every (dim, value) pair a question may point at, choice attributes included (#31)."""
    return policy.dimensions.value_pairs()


def log_facts(scenario: TriageScenario) -> Facts:
    facts = Facts()
    for event in scenario.log:
        facts.add(
            "log_event", event.id, event.registration or "", event.kind, clock.to_epoch(event.at)
        )
        for key, value in event.attrs.items():
            facts.add("log_attr", event.id, key, str(value))
    return facts


def question_facts(question: Question) -> Facts:
    facts = Facts()
    facts.add("question", question.id)
    for topic in TOPICS:
        facts.add("supported_topic", topic)
    return facts


TRIAGE_POLICY_KEYS = ("grace_minutes", "sync_lag_minutes")


def triage_facts(scenario: TriageScenario) -> Facts:
    facts = scenario_facts(scenario)
    facts.extend(log_facts(scenario))
    facts.extend(question_facts(scenario.question))
    for key in TRIAGE_POLICY_KEYS:
        facts.add("triage_policy", key, getattr(scenario.policy.triage, key))
    return facts


def candidate_id(question_id: str, fact: CandidateFact) -> str:
    return evidence_id("candidate", question_id, fact.relation, *fact.args)
