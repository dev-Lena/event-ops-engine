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


# --- query cache (#83) ---------------------------------------------------------------


def test_cached_results_follow_inserts_and_removals() -> None:
    with Engine(RULES) as engine:
        engine.insert("att", ("a1", "hot"))
        assert engine.rows("flagged") == [("a1",)]
        engine.insert("att", ("a2", "hot"))
        assert engine.rows("flagged") == [("a1",), ("a2",)]
        assert engine.rows("att", "a2") == [("a2", "hot")]
        engine.remove("att", ("a1", "hot"))
        assert engine.snapshot("flagged") == [("a2",)]
        assert engine.rows("att", "a1") == []


def test_one_engine_snapshot_per_relation_whatever_the_prefixes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with Engine(RULES) as engine:
        for i in range(20):
            engine.insert("att", (f"a{i}", "hot"))
        calls: list[str] = []
        original = engine._session.snapshot

        def counting(relation: str) -> object:
            calls.append(relation)
            return original(relation)

        monkeypatch.setattr(engine._session, "snapshot", counting)
        for i in range(20):
            assert engine.rows("flagged", f"a{i}") == [(f"a{i}",)]
        assert calls == ["flagged"]


def test_mutating_a_returned_list_leaves_the_cache_alone() -> None:
    with Engine(RULES) as engine:
        engine.insert("att", ("a1", "hot"))
        engine.snapshot("flagged").clear()
        engine.rows("flagged", "a1").append(("x",))
        assert engine.snapshot("flagged") == [("a1",)]
        assert engine.rows("flagged", "a1") == [("a1",)]
