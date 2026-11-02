"""Layer: lib. Turns a validated Scenario into engine facts and evidence ids.

Headcount conversion (docs/design.md 4): one registration becomes `party_size` attendees.
Registrations with unknown composition get attendees whose attributes are all "unknown".
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from . import bands, clock
from .model import (
    UNKNOWN,
    CandidateFact,
    Member,
    Question,
    Registration,
    Scenario,
    Session,
    TriageScenario,
)
from .policy import POLICY_KEYS, resolve_ratios, resolve_targets

Row = tuple[Any, ...]

DIM_GENDER = "gender"
DIM_AGE_BAND = "age_band"


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
    for key in POLICY_KEYS:
        facts.add("policy", session.id, key, getattr(policy.promotion, key))
    return facts


def member_attributes(member: Member | None, scenario: Scenario, session: Session) -> list[Row]:
    """(dim, value) pairs for one attendee; `member is None` means unknown composition."""
    if member is None:
        pairs: list[Row] = [(DIM_GENDER, UNKNOWN)]
        if scenario.policy.dimensions.age_band is not None:
            pairs.append((DIM_AGE_BAND, UNKNOWN))
        return pairs
    pairs = [(DIM_GENDER, member.gender.value)]
    age_dimension = scenario.policy.dimensions.age_band
    if age_dimension is not None:
        band = bands.age_band(member.birth_year, session.date.year, age_dimension.bands)
        pairs.append((DIM_AGE_BAND, band))
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
        for dim, value in member_attributes(member, scenario, session):
            facts.add("attendee_attr", attendee, dim, value)
    for event in registration.status_events:
        facts.add("status_event", registration.id, clock.to_epoch(event.at), event.status.value)
    return facts


def scenario_facts(scenario: Scenario) -> Facts:
    facts = Facts()
    facts.add("now", clock.to_epoch(scenario.now))
    for session in scenario.sessions:
        facts.extend(session_facts(scenario, session))
    for registration in scenario.registrations:
        facts.extend(registration_facts(scenario, registration))
    return facts


# --- module ① inquiry triage (docs/design.md 13) -------------------------------------

TOPICS = ("payment", "delivery", "duplicate", "deadline", "seat")
"""`supported_topic` facts. A topic is answered only once its type rules exist (#15-#21)."""

CANDIDATE_RELATIONS = {
    "asks_about": "topic",
    "about_registration": "registration",
    "about_session": "session",
    "about_event": "log",
}
"""Relations the interpreter may propose, and what their single argument must name."""


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


TRIAGE_POLICY_KEYS = ("grace_minutes",)


def triage_facts(scenario: TriageScenario) -> Facts:
    facts = scenario_facts(scenario)
    facts.extend(log_facts(scenario))
    facts.extend(question_facts(scenario.question))
    for key in TRIAGE_POLICY_KEYS:
        facts.add("triage_policy", key, getattr(scenario.policy.triage, key))
    return facts


def candidate_id(question_id: str, fact: CandidateFact) -> str:
    return evidence_id("candidate", question_id, fact.relation, *fact.args)
