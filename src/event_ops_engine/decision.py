"""Layer: lib. The decision contract shared by every module: a judgement plus its evidence."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class DecisionKind(StrEnum):
    RECOMMEND = "recommend"
    """Promotion recommended for the operator to run (never executed by the engine)."""
    HOLD = "hold"
    """A gap exists but promotion cannot help (e.g. the session is full); operator to decide."""
    ASK = "ask"
    """Input is incomplete; the operator must supply or confirm something."""


class Decision(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: DecisionKind
    session: str
    dim: str | None = None
    value: str | None = None
    need: int | None = None
    reasons: tuple[str, ...] = ()
    evidence: tuple[str, ...] = Field(min_length=1)
    message: str


class VerdictKind(StrEnum):
    """Module ① decision contract (docs/design.md 13)."""

    ACCEPT = "accept"
    """Exactly one cause, with evidence."""
    ASK = "ask"
    """No cause yet (facts missing) or several candidate causes; a person must supply or choose."""
    ABSTAIN = "abstain"
    """The question is outside the supported topics."""
    REJECT = "reject"
    """The interpreter's output failed validation: unknown relation, provenance or id."""


class Verdict(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: VerdictKind
    question: str
    cause: str | None = None
    causes: tuple[str, ...] = ()
    needs: tuple[str, ...] = ()
    evidence: tuple[str, ...] = Field(min_length=1)
    message: str
    trace: tuple[str, ...] = ()
