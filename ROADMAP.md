# Roadmap

Congruent ships publicly between **M1 and M3** — the honest, bounded tool is the product. Completeness is not the goal; a trustworthy verdict-or-counterexample is.

## Milestones

### M0 — Walking skeleton ✅
CLI parses two functions; Stage-1 differential tester only; produces a `Verdict` and a formatted report. Runs end-to-end on the difftest path.

- [x] Repo layout, packaging, CI scaffold
- [x] `Verdict` / `Counterexample` data model
- [x] `ir.parse_function` for the v1 Python subset (loud `UnsupportedConstruct`)
- [x] Fixed-width (two's-complement) concrete interpreter over the IR
- [x] `difftest` random + boundary generation from a typed signature
- [x] `cli` wires parse → difftest → report (exit codes 0/1/2)
- [x] Fixtures: two counterexample pairs, two equivalent pairs

### M1 — Symbolic core *(credibility milestone)* ✅
Integer/bool arithmetic + branches lowered to Z3; `UNSAT`/`SAT` → verdict; decode SAT models back to concrete counterexamples.

- [x] `symbolic` interpreter over the IR subset → Z3 expressions (continuation-passing path merge; early returns supported)
- [x] `solver` builds `(outputs differ)` over shared symbolic inputs and solves
- [x] Model decoding → `Counterexample`
- [x] Fixed-width (bitvector) integer model — Python-faithful floor `//`/`%`
- [x] `equiv` escalation: difftest → symbolic, with sound fallback to UNKNOWN

Known M1 limitations (not false proofs — they fall back to UNKNOWN): division/modulo by a non-constant or zero divisor isn't modeled; list params aren't symbolic yet.

### M2 — Bounded loops + arrays *(in progress)*
- [x] `for ... in range(...)` loops: unroll to depth `bound`, report the bound
- [x] Bounded model checking: in-bound assumption (loop trip count ≤ bound), so loop verdicts read "EQUIVALENT up to bound N"
- [x] Concrete interpreter caps loops at `bound` (difftest stays in the same domain)
- [x] Input preconditions: leading `assume(<expr>)` statements + CLI `--assume`, honored by both stages
- [x] `list[int]` inputs: bounded-length symbolic arrays, `len(xs)`, `for x in xs` iteration (proven); `xs[i]` reads run in difftest
- [ ] `xs[i]` indexing in *proofs* (needs per-access in-bounds guards under path conditions)
- [ ] `return` / `break` / `continue` inside loops
- [ ] List *outputs* (functions that build/return a list)
- [ ] Optionally bounded strings

### M3 — Demo + benchmarks *(in progress)*
- [x] Recall benchmark over the eval set with a zero-unsound-verdicts gate (`benchmarks/bench_recall.py`)
- [x] Timing-vs-bound benchmark (`benchmarks/bench_scaling.py`)
- [x] Eval set spanning truly-equivalent **and** subtly-broken pairs (off-by-one, overflow, loop/array bugs)
- [ ] README demo image showing a caught bug (the midpoint-overflow case)
- [ ] Curated gallery of real AI-refactor pairs (beyond the unit fixtures)

### M4 — Stretch
- [ ] C subset
- [ ] LLM-suggested refactors auto-checked
- [ ] Counterexample minimization (shrink to smallest failing input)
- [ ] Pluggable solver backend (CVC5) behind the `solver` abstraction

## Out of scope for v1 → future work

These are stated plainly in the README as current limitations. They are roadmap, not failure:

- Unbounded loops / recursion without a bound
- Floating-point exactness
- Side effects, I/O, global mutation
- Concurrency
- Heap aliasing and full object semantics
- Full Python language semantics (only a typed subset is supported)

The discipline of saying "no" here is what makes a "yes" verdict trustworthy.
