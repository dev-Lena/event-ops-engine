"""Engine wrapper: constant interning, input-relation store, strict retraction."""

import pytest

from event_ops_engine.engine import Engine

RULES = """
.decl att(a: symbol, v: symbol)
.decl flagged(a: symbol)
// a stray quote in a comment: "unbalanced
flagged(A) :- att(A, "hot").
"""


def test_constants_are_interned_even_with_a_stray_quote_in_a_comment() -> None:
    with Engine(RULES) as engine:
        engine.insert("att", ("a1", "hot"))
        engine.insert("att", ("a2", "cold"))
        assert engine.snapshot("flagged") == [("a1",)]


def test_remove_of_a_row_that_was_never_inserted_raises() -> None:
    with Engine(RULES) as engine:
        engine.insert("att", ("a1", "hot"))
        with pytest.raises(KeyError):
            engine.remove("att", ("zzz", "hot"))
        with pytest.raises(KeyError):
            engine.remove("nope", ("a1", "hot"))
        engine.remove("att", ("a1", "hot"))
        assert engine.snapshot("flagged") == []
        assert engine.snapshot("att") == []


def test_every_rule_file_ships_with_the_package() -> None:
    from importlib.resources import files

    from event_ops_engine.engine import RULE_FILES, RULES_DIR

    assert all((RULES_DIR / name).is_file() for name in RULE_FILES)
    assert {name for name in RULE_FILES} <= {
        p.name for p in files("event_ops_engine.rules").iterdir()
    }
