# Fixtures — the evaluation set

Each fixture is a Python module that pairs two functions to compare, plus the
expected verdict. This is the eval set Congruent is measured against: every new
capability should add fixtures, and recall over this set is reported in
`benchmarks/`.

## Convention

A fixture module defines:

- `original(...)` — the reference function.
- `candidate(...)` — the rewritten function under test.
- `EXPECTED` — `"EQUIVALENT"` or `"COUNTEREXAMPLE"`.
- `NOTE` — one line on what the pair exercises (and, for counterexamples, the
  kind of input that should break it).

Functions stay inside the supported v1 subset (typed params; int/bool;
arithmetic, comparisons, boolean logic; `if/else`; conditional expressions).
Loops and arrays arrive in M2 — see `../../ROADMAP.md`.

Every pair must be correct under the tool's semantics: integers are modeled as
fixed-width two's-complement, and scalar `int` inputs range over the **whole**
machine-int domain (not a small bound). A pair is only `EQUIVALENT` if it holds
for every input at the configured width — a loop summed against a closed form,
for instance, is *not* equivalent once overflow is in play, so it belongs in M2
with bounded input domains, not here.

## Files

- `midpoint_overflow.py` — `COUNTEREXAMPLE`: 32-bit overflow in `(lo + hi) // 2`.
- `off_by_one.py` — `COUNTEREXAMPLE`: `<=` changed to `<`; diverges at `x == 0`.
- `distribute.py` — `EQUIVALENT`: distributivity of `*` over `+` (holds mod 2**w).
- `abs_branch.py` — `EQUIVALENT`: ternary vs. if/else absolute value.
