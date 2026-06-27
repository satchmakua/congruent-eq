# Roadmap

Congruent ships publicly once the demo lands (M3) — the honest, bounded tool is
the product, not completeness. A trustworthy verdict-or-counterexample is the bar.

**Legend:** ✅ done · 🔜 next · ⬜ planned

---

## Done

### M0 — Walking skeleton ✅
Parse → fixed-width concrete interpreter → differential tester → `Verdict` → CLI
(exit codes 0/1/2). The pipeline runs end to end on the difftest path.

### M1 — Symbolic core ✅ *(credibility milestone)*
A from-scratch symbolic interpreter lowers each function to a Z3 bitvector
expression (continuation-passing path merge; early returns at top level).
`solver` asserts the outputs can differ: `UNSAT → EQUIVALENT`, `SAT →
COUNTEREXAMPLE` (model decoded to concrete inputs), else `UNKNOWN`. Python-faithful
floor `//`/`%`; sound `UNKNOWN` fallback for anything not yet modeled.

### M2 — Bounded loops, preconditions, arrays ✅
- `for ... in range(...)` and `for x in xs` — unrolled to `--bound` with bounded
  model checking (a non-wrapping in-bound assumption ⇒ honest "up to bound N").
- `assume(<expr>)` preconditions (inline + CLI `--assume`), honored by both stages.
- `list[int]` inputs as bounded Z3 arrays: `len(xs)`, iteration, and `xs[i]`.
- Runtime errors modeled as path-condition-guarded conditions: out-of-bounds
  `xs[i]` and divide-by-zero. Equivalence requires matching error behavior, so
  these are *proven*, not punted — no "assume in-bounds" caveat.

### M3 — Demo & benchmarks ✅ *(the "ship it" milestone)*
- Recall benchmark with a zero-unsound-verdicts gate (`benchmarks/bench_recall.py`).
- Timing-vs-bound benchmark (`benchmarks/bench_scaling.py`).
- Eval set spanning truly-equivalent **and** subtly-broken pairs.
- `examples/` gallery of realistic AI-refactor pairs + `run_gallery.py`, pinned by
  `tests/test_examples.py`.
- A committed terminal-style demo image (`docs/demo.svg`) leading the README.

---

## Next up (ordered)

### M4 — Early exit in loops ✅ *(`return` done; `break`/`continue` deferred)*
- Unified the symbolic interpreter into one state-threading pass carrying
  `(env, returned, return_value)`, so a `return` works *anywhere* — including
  inside a loop. Falling off the end without returning is folded into the error
  condition (Python would return None), which also removed an old `UnsupportedForProof`.
- Search now verifies: `contains` (early-return vs flag, EQ), `all_positive`
  (short-circuit, EQ), find-first off-by-one (CX).
- **Remaining:** `break` / `continue` (still rejected by the parser) — they need
  per-loop `broken` / per-iteration `continued` guards threaded like `returned`.

### M5 — Counterexample minimization ✅
- Symbolic-found counterexamples are shrunk with a few cheap incremental solver
  calls (`z3.Optimize` was tried first but hangs over bitvectors): minimize each
  list's length, then pull scalar ints to zero, locking in each gain.
- `--no-minimize` to skip it; minimized verdicts note `counterexample minimized`.
- difftest's own witnesses already use boundary values (`[]`, `0`, `-1`), so they
  are minimal by construction and returned as-is.

### M6 — List outputs ✅
- List literals `[a, b]` and `+` concatenation in the IR + both interpreters;
  built lists modeled as Z3 array + length, with a fast append path (`r + [x]`)
  and a general `concat`. Output lists bounded to length `bound` (longer outputs
  are out of scope), and a return-type-mismatch check guards the comparison.
- Output equivalence = equal length ∧ element-wise equal within bound.
- map (`x*2` vs `x+x`) and filter rewrites prove EQUIVALENT; off-by-one map /
  `>`-vs-`>=` filter / non-commutative concat yield counterexamples.

### M7 — Reach & robustness ✅ *(core; stretch items remain)*
- [x] `break` / `continue` inside loops — each loop owns a `broken` (accumulates,
      stops the loop) and a per-iteration `continued`, threaded like `returned`.
- [x] CVC5 cross-check backend — Z3 stays primary; CVC5 independently re-decides
      the same query (handed over as SMT-LIB2) under `--cross-check`. A
      disagreement downgrades the verdict to UNKNOWN. (`backends.py`)
- [x] Bounded strings — `str` modeled as a bounded sequence of code points
      (a character is a length-1 string), reusing the `SymList` machinery via a
      `kind` tag. Literals, `len`, `==`/`!=`, `+`, indexing, and iteration.
- [x] **C-subset front end** (`cfront.py`, via `pycparser`) — check C function
      pairs against the same engine. C's fixed-width `int` fits the bitvector
      model directly; C truncating `/`/`%` lower to dedicated IR ops. The CLI
      dispatches on the `.c` extension.
- [ ] *(Stretch)* auto-check LLM-suggested refactors (closed loop: AI proposes,
      Congruent verifies). Needs the Anthropic API, so it can't run offline.

---

## Where to go next

The honest bounded equivalence checker now covers a substantial Python subset
(plus a C front end) end to end. The only remaining item is the LLM closed-loop
demo, which needs network/API access — the v1 product is here.

---

## Out of scope for v1 → future work

Stated plainly in the README as current limitations — roadmap, not failure:

- Unbounded loops / recursion without a bound
- Floating-point exactness
- Side effects, I/O, global mutation
- Concurrency
- Heap aliasing and full object semantics
- Full Python language semantics (only a typed subset is supported)

The discipline of saying "no" here is what makes a "yes" verdict trustworthy.
