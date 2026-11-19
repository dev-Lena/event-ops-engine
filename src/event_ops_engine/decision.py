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
    CAP = "cap"
    """Hold one side of a ratio at a limit until the other catches up (operator applies it)."""


class DecisionPart(BaseModel):
    """A combination's share of a gender's promotion decision (#32)."""

    model_config = ConfigDict(frozen=True)

    dim: str
    value: str
    label: str
    need: int
    reasons: tuple[str, ...]


class Decision(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: DecisionKind
    session: str
    dim: str | None = None
    value: str | None = None
    need: int | None = None
    """The number in the message. For `recommend` / `hold` it is `shortfall` when there is
    one, else `ratio_diff`; for `cap` it is the recommended limit. Read the two fields below
    rather than decoding this from `reasons`."""
    reasons: tuple[str, ...] = ()
    evidence: tuple[str, ...] = Field(min_length=1)
    message: str
    parts: tuple[DecisionPart, ...] = ()
    """Combinations nested under this gender (#32): who, within `need`, the ads should reach."""
    shortfall: int | None = None
    """People missing below the target (`recommend` / `hold`); None when no target is short."""
    ratio_diff: int | None = None
    """How many fewer confirmed people this value has than its ratio partner (`recommend` /
    `hold`), set only on the trailing side once the allowed difference is exceeded. None
    otherwise, so None alone does not say the ratio is fine: the leading side gets a `cap`
    decision instead. A different count from `shortfall`, never added to it (#106)."""


class VerdictKind(StrEnum):
    """Module ① decision contract (docs/design.md 13)."""

    ACCEPT = "accept"
    """Exactly one cause, with evidence."""
    ASK = "ask"
    """No cause yet (facts missing), several candidate causes, or a candidate cause while
    facts about the question's own subject are still missing; a person must supply or choose."""
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
    dropped: tuple[str, ...] = ()
    """Candidate fact ids left out of reasoning because the interpreter was unsure."""
    trace: tuple[str, ...] = ()
