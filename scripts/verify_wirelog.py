"""Verify the wirelog syntax the event-ops-engine design relies on (handoff §6-1).

Each check prints PASS / FAIL / ERROR with the observed result so the report
can separate facts from opinions. Run with WIRELOG_LIB pointing at the
Intel-Mac build of libwirelog (or unset on Linux to use the wheel engine).

Expected result on wirelog 0.70.0: 27/28 PASS. The one FAIL (body binding
`Z = X - Y`) documents a known limitation; see docs/design.md 9.
"""

from __future__ import annotations

import re
import traceback

from event_ops_engine.engine import ensure_library_env

ensure_library_env()  # must run before importing pyrewire

import pyrewire  # noqa: E402
from pyrewire import BatchProgram, EasySession  # noqa: E402

RESULTS: list[tuple[str, str, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    RESULTS.append((name, "PASS" if ok else "FAIL", detail))


def open_session(src: str) -> EasySession:
    """EasySession whose intern table already knows every quoted constant in src.

    PyreWire cannot reverse-map an intern id it has not seen from Python, so
    inline facts and head constants come back as raw ids unless pre-interned.
    """
    s = EasySession(src)
    for const in set(re.findall(r'"([^"]*)"', src)):
        s.intern(const)
    return s


def batch(src: str, rels: list[str]) -> dict[str, set]:
    with open_session(src) as s:
        return {rel: set(s.snapshot(rel)) for rel in rels}


def batch_raw(src: str, rels: list[str]) -> dict[str, set]:
    """BatchProgram path: inline facts are auto-seeded (no load_all_facts)."""
    with BatchProgram.from_string(src) as p:
        p.optimize()
        with p.evaluate() as r:
            return {rel: set(r.relation(rel)) for rel in rels}


def check(name: str, fn) -> None:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - we want every failure recorded
        RESULTS.append((name, "ERROR", f"{type(exc).__name__}: {exc}"))
        traceback.print_exc()


# ---------------------------------------------------------------- 1. count / sum grouped by (session, dim, value)
def t_aggregate_grouped() -> None:
    src = """
.decl att(session: symbol, dim: symbol, value: symbol, n: int64)
.decl filled(session: symbol, dim: symbol, value: symbol, total: int64)
.decl cnt(session: symbol, dim: symbol, value: symbol, c: int64)
att("s1", "gender", "female", 1).
att("s1", "gender", "female", 2).
att("s1", "gender", "male", 1).
att("s2", "gender", "female", 1).
filled(S, D, V, sum(N)) :- att(S, D, V, N).
cnt(S, D, V, count(N)) :- att(S, D, V, N).
"""
    out = batch(src, ["filled", "cnt"])
    want_sum = {
        ("s1", "gender", "female", 3),
        ("s1", "gender", "male", 1),
        ("s2", "gender", "female", 1),
    }
    want_cnt = {
        ("s1", "gender", "female", 2),
        ("s1", "gender", "male", 1),
        ("s2", "gender", "female", 1),
    }
    record(
        "1a sum grouped by 3 symbol keys", out["filled"] == want_sum, f"got {sorted(out['filled'])}"
    )
    record("1b count grouped by 3 symbol keys", out["cnt"] == want_cnt, f"got {sorted(out['cnt'])}")


# ---------------------------------------------------------------- 1c. aggregate column NOT adjacent to group keys
def t_aggregate_nonadjacent() -> None:
    src = """
.decl att(session: symbol, n: int64, dim: symbol, value: symbol)
.decl filled(session: symbol, dim: symbol, value: symbol, total: int64)
att("s1", 1, "gender", "female").
att("s1", 2, "gender", "female").
att("s1", 5, "gender", "male").
filled(S, D, V, sum(N)) :- att(S, N, D, V).
"""
    out = batch(src, ["filled"])
    want = {("s1", "gender", "female", 3), ("s1", "gender", "male", 5)}
    record(
        "1c sum when aggregated column is not adjacent to keys",
        out["filled"] == want,
        f"got {sorted(out['filled'])}",
    )


# ---------------------------------------------------------------- 2. arithmetic and comparison
def t_arith_compare() -> None:
    src = """
.decl target(session: symbol, dim: symbol, value: symbol, lo: int64, hi: int64)
.decl filled(session: symbol, dim: symbol, value: symbol, total: int64)
.decl remaining(session: symbol, dim: symbol, value: symbol, r: int64)
.decl gap(session: symbol, dim: symbol, value: symbol, g: int64)
.decl full(session: symbol, dim: symbol, value: symbol)
.decl over_cap(session: symbol, dim: symbol, value: symbol)
target("s1", "gender", "female", 4, 6).
target("s1", "gender", "male", 4, 6).
target("s1", "age_band", "25-29", 2, 10).
filled("s1", "gender", "female", 6).
filled("s1", "gender", "male", 7).
filled("s1", "age_band", "25-29", 1).
remaining(S, D, V, Max - F) :- target(S, D, V, _, Max), filled(S, D, V, F).
gap(S, D, V, Min - F) :- target(S, D, V, Min, _), filled(S, D, V, F), Min - F > 0.
full(S, D, V) :- remaining(S, D, V, R), R <= 0.
over_cap(S, D, V) :- target(S, D, V, _, Max), filled(S, D, V, F), F > Max.
"""
    out = batch(src, ["remaining", "gap", "full", "over_cap"])
    record(
        "2a R = Max - F (subtraction in body, negative result)",
        out["remaining"]
        == {
            ("s1", "gender", "female", 0),
            ("s1", "gender", "male", -1),
            ("s1", "age_band", "25-29", 9),
        },
        f"got {sorted(out['remaining'])}",
    )
    record(
        "2b G = Min - F, G > 0 filter",
        out["gap"] == {("s1", "age_band", "25-29", 1)},
        f"got {sorted(out['gap'])}",
    )
    record(
        "2c R <= 0",
        out["full"] == {("s1", "gender", "female"), ("s1", "gender", "male")},
        f"got {sorted(out['full'])}",
    )
    record(
        "2d F > Max",
        out["over_cap"] == {("s1", "gender", "male")},
        f"got {sorted(out['over_cap'])}",
    )


# ---------------------------------------------------------------- 2e. arithmetic in head
def t_arith_head() -> None:
    src = """
.decl a(x: int64, y: int64)
.decl d(x: int64, z: int64)
a(10, 3).
d(X, X - Y - 1) :- a(X, Y).
"""
    out = batch(src, ["d"])
    record("2e arithmetic in head (X - Y - 1)", out["d"] == {(10, 6)}, f"got {sorted(out['d'])}")


# ---------------------------------------------------------------- 3. latest status (LWW): max(ts) then join back
def t_lww() -> None:
    src = """
.decl status_event(reg: symbol, ts: int64, status: symbol)
.decl latest_ts(reg: symbol, ts: int64)
.decl current_status(reg: symbol, status: symbol)
status_event("r1", 100, "submitted").
status_event("r1", 200, "pending_payment").
status_event("r1", 300, "confirmed").
status_event("r2", 100, "submitted").
status_event("r2", 150, "cancelled").
latest_ts(R, max(T)) :- status_event(R, T, _).
current_status(R, S) :- latest_ts(R, T), status_event(R, T, S).
"""
    out = batch(src, ["current_status"])
    record(
        "3 latest status via max(ts) + join",
        out["current_status"] == {("r1", "confirmed"), ("r2", "cancelled")},
        f"got {sorted(out['current_status'])}",
    )


# ---------------------------------------------------------------- 3b. LWW with status column between key and ts
def t_lww_nonadjacent() -> None:
    src = """
.decl status_event(reg: symbol, status: symbol, ts: int64)
.decl latest_ts(reg: symbol, ts: int64)
.decl current_status(reg: symbol, status: symbol)
status_event("r1", "submitted", 100).
status_event("r1", "confirmed", 300).
status_event("r1", "pending_payment", 200).
latest_ts(R, max(T)) :- status_event(R, _, T).
current_status(R, S) :- latest_ts(R, T), status_event(R, S, T).
"""
    out = batch(src, ["current_status"])
    record(
        "3b max(ts) when ts is not adjacent to key",
        out["current_status"] == {("r1", "confirmed")},
        f"got {sorted(out['current_status'])}",
    )


# ---------------------------------------------------------------- 3c. min + max per group, spread in the head, after removal (#91)
def t_min_spread() -> None:
    src = """
.decl age(s: symbol, g: symbol, a: symbol, n: int64)
.decl lo(s: symbol, g: symbol, n: int64)
.decl hi(s: symbol, g: symbol, n: int64)
.decl spread(s: symbol, g: symbol, n: int64)
lo(S, G, min(N)) :- age(S, G, _, N).
hi(S, G, max(N)) :- age(S, G, _, N).
spread(S, G, H - L) :- hi(S, G, H), lo(S, G, L).
"""
    with open_session(src) as s:
        for const in ["s1", "female", "male", "a1", "a2", "a3", "a4"]:
            s.intern(const)
        rows = [("s1", "female", "a1", 27), ("s1", "female", "a2", 41)]
        rows += [("s1", "female", "a3", 29), ("s1", "male", "a4", 33)]
        for row in rows:
            s.insert("age", list(row))
        before = set(s.snapshot("spread"))
        s.remove("age", ["s1", "female", "a2", 41])
        after = set(s.snapshot("spread"))
    record(
        "3c min/max per group, spread via head arithmetic, updated after removal",
        before == {("s1", "female", 14), ("s1", "male", 0)}
        and after == {("s1", "female", 2), ("s1", "male", 0)},
        f"before={sorted(before)} after={sorted(after)}",
    )


# ---------------------------------------------------------------- 3d. head division and precedence (#91 C)
def t_head_division() -> None:
    src = """
.decl a(x: int64, y: int64)
.decl r(name: symbol, z: int64)
r("div", X / 2) :- a(X, Y).
r("prec", X - Y / 2) :- a(X, Y).
r("chain", X - Y / 2 + X) :- a(X, Y).
"""
    with open_session(src) as s:
        s.insert("a", [11, 2])
        got = set(s.snapshot("r"))
    record(
        "3d head integer division truncates, / binds tighter than - and +",
        got == {("div", 5), ("prec", 10), ("chain", 21)},
        f"got {sorted(got)}",
    )


# ---------------------------------------------------------------- 4. stratified negation
def t_negation() -> None:
    src = """
.decl target(session: symbol, dim: symbol, value: symbol, lo: int64)
.decl filled(session: symbol, dim: symbol, value: symbol, total: int64)
.decl filled_or_zero(session: symbol, dim: symbol, value: symbol, total: int64)
.decl no_filled(session: symbol, dim: symbol, value: symbol)
target("s1", "gender", "female", 4).
target("s1", "gender", "male", 4).
filled("s1", "gender", "female", 2).
no_filled(S, D, V) :- target(S, D, V, _), !filled(S, D, V, _).
filled_or_zero(S, D, V, F) :- filled(S, D, V, F).
filled_or_zero(S, D, V, 0) :- no_filled(S, D, V).
"""
    out = batch(src, ["no_filled", "filled_or_zero"])
    record(
        "4a negation !filled(S,D,V,_) with wildcard",
        out["no_filled"] == {("s1", "gender", "male")},
        f"got {sorted(out['no_filled'])}",
    )
    record(
        "4b default-0 via negation (empty group -> 0)",
        out["filled_or_zero"] == {("s1", "gender", "female", 2), ("s1", "gender", "male", 0)},
        f"got {sorted(out['filled_or_zero'])}",
    )


# ---------------------------------------------------------------- 5. retraction in EasySession (snapshot mode)
def t_retract_snapshot() -> None:
    src = """
.decl att(session: symbol, dim: symbol, value: symbol, n: int64)
.decl target(session: symbol, dim: symbol, value: symbol, hi: int64)
.decl filled(session: symbol, dim: symbol, value: symbol, total: int64)
.decl full(session: symbol, dim: symbol, value: symbol)
target("s1", "gender", "female", 3).
filled(S, D, V, sum(N)) :- att(S, D, V, N).
full(S, D, V) :- filled(S, D, V, F), target(S, D, V, Max), F >= Max.
"""
    with open_session(src) as s:
        s.insert("att", ["s1", "gender", "female", 2])
        s.insert("att", ["s1", "gender", "female", 1])
        before_full = set(s.snapshot("full"))
        before_filled = set(s.snapshot("filled"))
        s.remove("att", ["s1", "gender", "female", 1])
        after_full = set(s.snapshot("full"))
        after_filled = set(s.snapshot("filled"))
    record(
        "5a snapshot: sum + full before retraction",
        before_filled == {("s1", "gender", "female", 3)}
        and before_full == {("s1", "gender", "female")},
        f"filled={sorted(before_filled)} full={sorted(before_full)}",
    )
    record(
        "5b snapshot: full retracted after remove (sum recomputed)",
        after_filled == {("s1", "gender", "female", 2)} and after_full == set(),
        f"filled={sorted(after_filled)} full={sorted(after_full)}",
    )


# ---------------------------------------------------------------- 5c. retraction in EasySession (incremental step mode)
def t_retract_step() -> None:
    src = """
.decl att(session: symbol, dim: symbol, value: symbol, n: int64)
.decl target(session: symbol, dim: symbol, value: symbol, hi: int64)
.decl filled(session: symbol, dim: symbol, value: symbol, total: int64)
.decl full(session: symbol, dim: symbol, value: symbol)
target("s1", "gender", "female", 3).
filled(S, D, V, sum(N)) :- att(S, D, V, N).
full(S, D, V) :- filled(S, D, V, F), target(S, D, V, Max), F >= Max.
"""
    with open_session(src) as s:
        s.insert("att", ["s1", "gender", "female", 2])
        s.insert("att", ["s1", "gender", "female", 1])
        d1 = s.step()
        s.remove("att", ["s1", "gender", "female", 1])
        d2 = s.step()
    full1 = {(row, diff) for rel, row, diff in d1 if rel == "full"}
    full2 = {(row, diff) for rel, row, diff in d2 if rel == "full"}
    filled2 = {(row, diff) for rel, row, diff in d2 if rel == "filled"}
    record("5c step: full derived (+1)", full1 == {(("s1", "gender", "female"), 1)}, f"d1={d1}")
    record(
        "5d step: full retracted (-1) and filled 3->2 after remove",
        full2 == {(("s1", "gender", "female"), -1)}
        and filled2 == {(("s1", "gender", "female", 3), -1), (("s1", "gender", "female", 2), 1)},
        f"d2={d2}",
    )


# ---------------------------------------------------------------- 6. retraction with negation (reopen after full)
def t_retract_negation() -> None:
    src = """
.decl att(session: symbol, dim: symbol, value: symbol, n: int64)
.decl target(session: symbol, dim: symbol, value: symbol, hi: int64)
.decl filled(session: symbol, dim: symbol, value: symbol, total: int64)
.decl full(session: symbol, dim: symbol, value: symbol)
.decl open(session: symbol, dim: symbol, value: symbol)
target("s1", "gender", "female", 3).
filled(S, D, V, sum(N)) :- att(S, D, V, N).
full(S, D, V) :- filled(S, D, V, F), target(S, D, V, Max), F >= Max.
open(S, D, V) :- target(S, D, V, _), !full(S, D, V).
"""
    with open_session(src) as s:
        o0 = set(s.snapshot("open"))
        s.insert("att", ["s1", "gender", "female", 3])
        o1 = set(s.snapshot("open"))
        s.remove("att", ["s1", "gender", "female", 3])
        o2 = set(s.snapshot("open"))
    record(
        "6 open (negation of full) flips closed then reopens after retraction",
        o0 == {("s1", "gender", "female")} and o1 == set() and o2 == {("s1", "gender", "female")},
        f"o0={sorted(o0)} o1={sorted(o1)} o2={sorted(o2)}",
    )


# ---------------------------------------------------------------- 7. mixed symbol / int in one relation, int compared to constant
def t_mixed_types() -> None:
    src = """
.decl reg(id: symbol, session: symbol, party: symbol, m: int64, f: int64)
.decl headcount(id: symbol, dim: symbol, value: symbol, n: int64)
.decl unknown(id: symbol)
reg("r1", "s1", "solo_female", 0, 1).
reg("r2", "s1", "pair_mixed", 1, 1).
reg("r3", "s1", "group", 3, 2).
reg("r4", "s1", "legacy", -1, -1).
headcount(R, "gender", "male", M) :- reg(R, _, _, M, _), M > 0.
headcount(R, "gender", "female", F) :- reg(R, _, _, _, F), F > 0.
unknown(R) :- reg(R, _, _, M, _), M < 0.
"""
    out = batch(src, ["headcount", "unknown"])
    want = {
        ("r1", "gender", "female", 1),
        ("r2", "gender", "male", 1),
        ("r2", "gender", "female", 1),
        ("r3", "gender", "male", 3),
        ("r3", "gender", "female", 2),
    }
    record(
        "7a string constants in head + int filter",
        out["headcount"] == want,
        f"got {sorted(out['headcount'])}",
    )
    record(
        "7b negative int literal compare (M < 0)",
        out["unknown"] == {("r4",)},
        f"got {sorted(out['unknown'])}",
    )


# ---------------------------------------------------------------- 8. count over derived relation (two-level aggregation)
def t_two_level() -> None:
    src = """
.decl att(session: symbol, dim: symbol, value: symbol, n: int64)
.decl filled(session: symbol, dim: symbol, value: symbol, total: int64)
.decl session_total(session: symbol, total: int64)
att("s1", "gender", "female", 2).
att("s1", "gender", "male", 1).
att("s1", "gender", "male", 1).
filled(S, D, V, sum(N)) :- att(S, D, V, N).
session_total(S, sum(T)) :- filled(S, "gender", _, T).
"""
    out = batch(src, ["session_total"])
    record(
        "8 sum over a derived aggregate (two strata)",
        out["session_total"] == {("s1", 4)},
        f"got {sorted(out['session_total'])}",
    )


# ---------------------------------------------------------------- 9. ratio imbalance: compare two values of same dim
def t_ratio() -> None:
    src = """
.decl filled(session: symbol, dim: symbol, value: symbol, total: int64)
.decl ratio_target(session: symbol, dim: symbol, a: symbol, b: symbol)
.decl imbalance(session: symbol, dim: symbol, short: symbol, diff: int64)
filled("s1", "gender", "female", 2).
filled("s1", "gender", "male", 5).
ratio_target("s1", "gender", "male", "female").
imbalance(S, D, B, Fa - Fb) :- ratio_target(S, D, A, B), filled(S, D, A, Fa), filled(S, D, B, Fb), Fa > Fb.
imbalance(S, D, A, Fb - Fa) :- ratio_target(S, D, A, B), filled(S, D, A, Fa), filled(S, D, B, Fb), Fb > Fa.
"""
    out = batch(src, ["imbalance"])
    record(
        "9 ratio imbalance: self-join on filled, pick short side",
        out["imbalance"] == {("s1", "gender", "female", 3)},
        f"got {sorted(out['imbalance'])}",
    )


# ---------------------------------------------------------------- 10. EasySession: insert facts for several relations, snapshot a derived one; symbol round-trip
def t_session_symbols() -> None:
    src = """
.decl target(session: symbol, dim: symbol, value: symbol, lo: int64, hi: int64)
.decl filled(session: symbol, dim: symbol, value: symbol, total: int64)
.decl gap(session: symbol, dim: symbol, value: symbol, g: int64)
gap(S, D, V, Min - F) :- target(S, D, V, Min, _), filled(S, D, V, F), Min - F > 0.
"""
    with open_session(src) as s:
        s.insert("target", ["tech-meetup/2026-11-07", "age_band", "25-29", 4, 10])
        s.insert("filled", ["tech-meetup/2026-11-07", "age_band", "25-29", 1])
        g = set(s.snapshot("gap"))
    record(
        "10 EasySession symbols with '/' and '-' round-trip",
        g == {("tech-meetup/2026-11-07", "age_band", "25-29", 3)},
        f"got {sorted(g)}",
    )


# ---------------------------------------------------------------- 11. BatchProgram path (ints only) and body `G = expr` binding
def t_batch_ints() -> None:
    src = """
.decl a(k: int64, v: int64)
.decl t(k: int64, s: int64)
a(1, 2). a(1, 3). a(2, 5).
t(K, sum(V)) :- a(K, V).
"""
    out = batch_raw(src, ["t"])
    record(
        "11a BatchProgram: inline facts seeded once, sum ok (no load_all_facts)",
        out["t"] == {(1, 5), (2, 5)},
        f"got {sorted(out['t'])}",
    )


def t_body_binding() -> None:
    src = """
.decl a(x: int64, y: int64)
.decl d(x: int64, z: int64)
a(10, 3).
d(X, Z) :- a(X, Y), Z = X - Y.
"""
    out = batch(src, ["d"])
    record(
        "11b body binding Z = X - Y (expected per docs; empty = unsupported)",
        out["d"] == {(10, 7)},
        f"got {sorted(out['d'])}",
    )


def t_reserved_names() -> None:
    bad = []
    for col in ["min", "max", "count", "sum"]:
        try:
            BatchProgram.from_string(f".decl t(id: symbol, {col}: int64)\n").close()
        except Exception:
            bad.append(col)
    record(
        "11c column names min/max/count/sum are rejected (reserved)",
        bad == ["min", "max", "count", "sum"],
        f"rejected={bad}",
    )


def t_parentheses() -> None:
    src = ".decl a(x: int64, y: int64)\n.decl r(z: int64)\nr(X - (Y - X)) :- a(X, Y).\n"
    try:
        BatchProgram.from_string(src).close()
        rejected = False
    except Exception:
        rejected = True
    record(
        "11d parentheses in arithmetic are a parse error (split into relations)",
        rejected,
        f"rejected={rejected}",
    )


if __name__ == "__main__":
    print("pyrewire", pyrewire.__version__, "wirelog", pyrewire.wirelog_version())
    for fn in [
        t_aggregate_grouped,
        t_aggregate_nonadjacent,
        t_arith_compare,
        t_arith_head,
        t_lww,
        t_lww_nonadjacent,
        t_min_spread,
        t_head_division,
        t_negation,
        t_retract_snapshot,
        t_retract_step,
        t_retract_negation,
        t_mixed_types,
        t_two_level,
        t_ratio,
        t_session_symbols,
        t_batch_ints,
        t_body_binding,
        t_reserved_names,
        t_parentheses,
    ]:
        check(fn.__name__, fn)
    print()
    for name, status, detail in RESULTS:
        print(f"[{status}] {name}\n        {detail}")
    print()
    print("PASS", sum(1 for r in RESULTS if r[1] == "PASS"), "/", len(RESULTS))
