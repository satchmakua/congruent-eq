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

Functions stay inside the supported v1 subset (typed params; int/bool/list[int];
`if/else`; bounded `for range`). See `../../ROADMAP.md`.

## Files

- `midpoint_overflow.py` — `COUNTEREXAMPLE`: 32-bit overflow in `(lo + hi) // 2`.
- `sum_to_n.py` — `EQUIVALENT`: closed form vs. accumulating loop.
