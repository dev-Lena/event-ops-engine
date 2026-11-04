"""Layer: services. Wraps PyreWire/wirelog and absorbs the 0.70.0 constraints (docs/design.md 9).

- Every quoted constant in the rule files is interned before use so symbol columns come
  back as strings.
- All data facts are inserted from Python; the .dl files hold no facts.
- `EasySession.snapshot` returns nothing for input (EDB) relations, so the wrapper keeps
  its own copy of every inserted fact and serves those relations from it.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Sequence
from importlib.resources import files
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from .facts import Facts, Row

RULES_DIR = Path(str(files("event_ops_engine.rules")))
"""The rule files: `rules/` at the repo root, packaged as `event_ops_engine.rules` (#70)."""
RULE_FILES = ("ontology.dl", "capacity.dl", "promotion.dl", "triage.dl")
LINE_COMMENT = re.compile(r"//[^\n]*")
QUOTED_CONSTANT = re.compile(r'"([^"\n]*)"')
WIRELOG_LIB_ENV = "WIRELOG_LIB"


def load_rules(rules_dir: Path = RULES_DIR, files: Sequence[str] = RULE_FILES) -> str:
    return "\n".join((rules_dir / name).read_text(encoding="utf-8") for name in files)


def default_library_path(repo_root: Path | None = None) -> Path | None:
    """A locally built engine (scripts/build-wirelog.sh), if present."""
    root = repo_root or Path(__file__).resolve().parents[2]
    for name in ("libwirelog.1.dylib", "libwirelog.so.1"):
        candidate = root / "vendor" / "wirelog" / "build" / name
        if candidate.is_file():
            return candidate
    return None


def ensure_library_env() -> None:
    """Point PyreWire at the local build when WIRELOG_LIB is unset (no-op otherwise)."""
    if os.environ.get(WIRELOG_LIB_ENV):
        return
    local = default_library_path()
    if local is not None:
        os.environ[WIRELOG_LIB_ENV] = str(local)


class Engine:
    """One evaluation session over the rule program. Use as a context manager."""

    def __init__(self, rules_src: str | None = None) -> None:
        # PyreWire resolves WIRELOG_LIB at import time, so the env is set before importing.
        ensure_library_env()
        from pyrewire import EasySession

        src = load_rules() if rules_src is None else rules_src
        self._session = EasySession(src)
        self._inputs: dict[str, dict[Row, int]] = {}
        # Comments are stripped first so a stray quote in one cannot hide a real constant.
        for constant in set(QUOTED_CONSTANT.findall(LINE_COMMENT.sub("", src))):
            self._session.intern(constant)

    def insert(self, relation: str, row: Row) -> None:
        row = tuple(row)
        self._session.insert(relation, list(row))
        store = self._inputs.setdefault(relation, {})
        store[row] = store.get(row, 0) + 1

    def remove(self, relation: str, row: Row) -> None:
        """Retract one previously inserted row. A row that was never inserted is an error."""
        row = tuple(row)
        store = self._inputs.get(relation, {})
        if row not in store:
            raise KeyError(f"{relation}{row}: not an inserted fact")
        self._session.remove(relation, list(row))
        store[row] -= 1
        if store[row] == 0:
            del store[row]

    def load(self, facts: Facts) -> None:
        for relation, rows in facts.rows.items():
            for row in rows:
                self.insert(relation, row)

    def retract(self, facts: Facts) -> None:
        for relation, rows in facts.rows.items():
            for row in rows:
                self.remove(relation, row)

    def snapshot(self, relation: str) -> list[tuple[Any, ...]]:
        """Rows of a derived relation from the engine, or of an input relation from the store."""
        if relation in self._inputs:
            return sorted(self._inputs[relation])
        return sorted(tuple(row) for row in self._session.snapshot(relation))

    def rows(self, relation: str, *prefix: Any) -> list[tuple[Any, ...]]:
        """Rows of `relation` whose leading columns equal `prefix`."""
        return [row for row in self.snapshot(relation) if row[: len(prefix)] == prefix]

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def contributors_by_value(engine: Engine, session_id: str) -> dict[tuple[str, str], list[str]]:
    """(dim, value) -> sorted registration ids whose confirmed attendees carry that value.

    Built once per session from three snapshots; callers look every value up in it.
    """
    seated = {row[1] for row in engine.rows("seat", session_id)}
    registration_of = {row[1]: row[0] for row in engine.snapshot("attendee")}
    found: dict[tuple[str, str], set[str]] = {}
    for attendee, dim, value in engine.snapshot("attendee_attr"):
        if attendee in seated:
            found.setdefault((str(dim), str(value)), set()).add(registration_of[attendee])
    return {key: sorted(regs) for key, regs in found.items()}


def unique(items: Iterable[str]) -> list[str]:
    seen: dict[str, None] = {}
    for item in items:
        seen.setdefault(item, None)
    return list(seen)
