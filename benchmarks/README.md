# Benchmarks

Two questions this directory answers:

1. **Recall on known pairs** — `bench_recall.py` runs `congruent.check` over every
   `tests/fixtures/` pair and tabulates the verdict against its declared
   `EXPECTED`. The headline invariant: **zero unsound verdicts** (no false
   `EQUIVALENT`, no false `COUNTEREXAMPLE`). Exits non-zero if any verdict is
   unsound, so it doubles as a CI gate. `tests/test_benchmarks.py` asserts the
   same.

2. **Cost vs. bound** — `bench_scaling.py` times the symbolic stage on the
   loop/array fixtures as `--bound` grows, making the scaling story explicit.

3. **Independent oracles** — the interpreter is the ground truth every other
   check trusts, so two oracles validate *it* against references that share no
   code with Congruent. `realpy_fuzz.py` diffs generated functions against real
   Python (semantics, run wide so nothing overflows). `numpy_oracle.py` covers
   the complementary half — the two's-complement **wrapping** — against numpy's
   C fixed-width scalars at small widths where overflow is routine (and matches
   Congruent's arithmetic exhaustively over every 8-bit operand pair). Both are
   pinned by a deterministic slice in the test suite (`test_realpy_oracle.py`,
   `test_numpy_oracle.py`).

## Run

```bash
python benchmarks/bench_recall.py            # add --bound N to change the bound
python benchmarks/bench_scaling.py           # add --bounds 2,4,8,16,32
```

Both add `src/` to the path themselves, so no install/`PYTHONPATH` is needed.

## Sample output

```
fixture                 expected        verdict         time
------------------------------------------------------------
array_len_count         EQUIVALENT      EQUIVALENT        3.2ms  ok
loop_reorder            EQUIVALENT      EQUIVALENT        6.1ms  ok
midpoint_overflow       COUNTEREXAMPLE  COUNTEREXAMPLE        -  ok
sum_to_n                EQUIVALENT      EQUIVALENT       21.1ms  ok
...
10/10 verdicts match expectation; 0 unsound
```

## The scaling edge (measured)

Where the symbolic stage actually starts to hurt, measured 2026-07-13 on one
consumer Windows 11 box (Python 3.11, z3-solver 4.16, 32-bit ints, `EQUIVALENT`
proofs — the expensive path, since a proof must close the whole space):

| fixture | b=8 | b=32 | b=128 | b=256 | b=512 | b=1024 |
| --- | --- | --- | --- | --- | --- | --- |
| `loop_reorder` (scalar loop, reversed accumulation) | 28ms | 77ms | 0.58s | 3.4s | 16.9s | **102s** |
| `sum_to_n` (loop vs. nonlinear closed form) | 31ms | 51ms | 0.38s | 1.4s | 8.8s | 39s |
| `array_len_count` (list iteration vs. `len`) | 27ms | 65ms | 0.28s | 0.66s | 2.2s | 7.9s |
| `array_sum_reorder` (two list loops, reordered) | 34ms | 94ms | 0.37s | 0.73s | 1.7s | 2.9s |
| `water_bill` example (~50-line billing routine) | 0.12s | 0.12s | — | — | — | — (0.21s at b=64) |

The honest envelope on this hardware:

- **b ≤ 32** — interactive (≤~0.1s), and where real refactor bugs live:
  every counterexample in the gallery and fixture set manifests at tiny inputs
  (the small-scope hypothesis is why the default is `--bound 8`).
- **b ≤ 128** — sub-second. Fine for CI.
- **b = 256–512** — seconds to tens of seconds; noticeable but usable.
- **b = 1024** — minutes for scalar-loop pairs. This is the cliff. Growth for
  the worst fixture is ~6× per bound doubling past 256, so b=2048 would be
  tens of minutes — plan accordingly or don't go there.

Two shape notes: unrolled *scalar* loops (where each iteration compounds
arithmetic on one accumulator) hit the cliff hardest, and nonlinear terms
(`sum_to_n`'s `n*(n+1)//2`) cost more than linear ones; list-driven loops scale
much more gently. Integer width barely matters in this range (16 vs. 64-bit is
within noise at b=32). Line count is not what costs — the ~50-line `water_bill`
example proves in ~0.1s because its only loop is a single shallow pass over the
input list; a function's price is set by its loop/list depth, not its length.

### The genuinely hard case: symbolic × symbolic (nonlinear bitvectors)

The tables above all multiply by *constants*. The wall is different when a loop
multiplies two *symbolic* values each iteration — e.g. Horner's method
(`y = y * x + c`, the `examples/polyval.py` numpy entry), where the proof
obligation is a polynomial with symbolic coefficients. That is nonlinear
bitvector arithmetic, the classic case a bit-blasting SMT solver chokes on, and
it explodes with *both* degree and width:

| polyval (`y = y*x + c`) | 8-bit | 16-bit | 32-bit |
| --- | --- | --- | --- |
| bound 2 (degree ≤ 1) | **0.7s** | > 30s | > 30s |
| bound 3 (degree ≤ 2) | ~18s | — | > 30s |
| bound 4 (degree ≤ 3) | > 30s | — | > 30s |

So an EQUIVALENT proof here is only practical at small width *and* small bound;
everything else returns UNKNOWN. This is why `check()` takes a `timeout_ms`:
without it, a 32-bit polyval query makes Z3 spin **indefinitely** — a true hang.
With it, the solver gives up cleanly and the verdict is an honest UNKNOWN. A
false EQUIVALENT is never produced either way. The lesson for users: if a rewrite
multiplies unknowns by unknowns in a loop, expect UNKNOWN unless you shrink the
width/bound — and know that UNKNOWN means "not decided," never "not equivalent."
