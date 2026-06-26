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

Functions stay inside the supported subset (typed params; int/bool/list[int];
arithmetic, comparisons, boolean logic; `if/else`; conditional expressions;
`for ... in range(...)` and `for x in xs` loops without `return` inside;
`len(xs)` and `xs[i]` reads). See `../../ROADMAP.md`.

`list[int]` inputs are bounded to length `--bound`, so an array verdict reads
"holds for lists up to length N". Out-of-bounds `xs[i]` and divide-by-zero are
modeled as matching runtime errors, so indexed functions are proven soundly
(a rewrite that crashes where the original didn't is a counterexample).

Every pair must be correct under the tool's semantics: integers are modeled as
fixed-width two's-complement, and scalar `int` inputs range over the **whole**
machine-int domain. For loop-free pairs, `EQUIVALENT` means equal at every
input. For pairs with loops, the verdict is bounded: loops are checked up to
`--bound` iterations, and inputs that would drive more are out of scope — so a
loop pair must be equivalent for *all* inputs whose loop stays within the bound
(a loop summed against a closed form fails this once overflow bites, and also
needs an `n >= 0` precondition the tool can't yet express — hence it's not here).

## Files

- `midpoint_overflow.py` — `COUNTEREXAMPLE`: 32-bit overflow in `(lo + hi) // 2`.
- `off_by_one.py` — `COUNTEREXAMPLE`: `<=` changed to `<`; diverges at `x == 0`.
- `loop_off_by_one.py` — `COUNTEREXAMPLE`: `range(n)` vs `range(n + 1)`.
- `distribute.py` — `EQUIVALENT`: distributivity of `*` over `+` (holds mod 2**w).
- `abs_branch.py` — `EQUIVALENT`: ternary vs. if/else absolute value.
- `loop_reorder.py` — `EQUIVALENT`: reversed loop accumulation (bounded).
- `sum_to_n.py` — `EQUIVALENT` under `assume(n >= 0)`: closed form vs. loop.
- `array_len_count.py` — `EQUIVALENT`: `len(xs)` vs. manual count.
- `array_sum_reorder.py` — `EQUIVALENT`: `total + x` vs. `x + total` over a list.
- `array_first.py` — `EQUIVALENT`: guarded `xs[0]` two ways (indexing in proofs).
- `array_count_off_by_one.py` — `COUNTEREXAMPLE`: `>` vs `>=` counting over a list.

A fixture may declare an input precondition with a leading `assume(<expr>)`
(see `sum_to_n.py`); the pair only needs to be equivalent where the precondition
holds.
