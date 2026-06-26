# Congruent

> Given an original function and an AI-rewritten one, **prove** behavioral equivalence within bounds — or return the concrete input that breaks it.

Coding agents refactor, migrate, and "optimize" code constantly. The honest answer to *"did this preserve behavior?"* is usually tests plus vibes. Congruent gives a real answer for a deliberately narrow slice of the problem: **`EQUIVALENT up to bound N`** or **`COUNTEREXAMPLE: <concrete input>`** — no magic in between.

It's equivalence checking (the EDA/formal-methods kind) pointed at the problem of trusting AI-generated code.

---

## Scope (read this first)

The credibility of this tool is its honesty about what it does and doesn't do. v1 is intentionally small.

| In scope (v1) | Out of scope (v1 — see [ROADMAP.md](ROADMAP.md)) |
| --- | --- |
| Pure, deterministic functions (no I/O, no global mutation) | Side effects, I/O, concurrency |
| Bounded inputs: machine ints, bools, fixed-length arrays/lists | Floating-point exactness |
| Integer/boolean arithmetic, comparisons, branches | Unbounded loops/recursion (only bounded, unrolled to depth `k`) |
| Bounded loops, unrolled to depth `k` (reported honestly) | Heap aliasing, full object semantics |
| One language: a **Python** subset (C is a stretch goal) | Full language semantics |

Two outputs only:

- **`EQUIVALENT up to bound N`** — no diverging input exists within the bound.
- **`COUNTEREXAMPLE: <input>`** — a concrete input where the two functions disagree, with both outputs.

Congruent never claims unconditional soundness. Every verdict carries its bound and assumptions.

---

## How it works

Cheap checks first, expensive proof only when needed:

1. **Differential testing** (`difftest.py`) — property-based random + boundary inputs. Kills obvious non-equivalence in milliseconds. A counterexample here ends the run.
2. **Symbolic execution → SMT** (`symbolic.py` + `solver.py`) — translate both functions' bounded behavior into logical constraints, assert *inputs equal ∧ outputs differ*, and ask [Z3](https://github.com/Z3Prover/z3). `UNSAT` = equivalent within bound; `SAT` = the model decodes back to a concrete counterexample.
3. **Bounded model checking** — unroll loops/recursion to depth `k`, verify up to that bound, report the bound.

```
input: fn_original, fn_candidate (source) + bound config
  ├─ parse → normalized typed IR        (ir.py)
  ├─ Stage 1: differential tester ──► counterexample? ─► REPORT   (difftest.py)
  ├─ Stage 2: symbolic engine                                     (symbolic.py)
  │     • symbolically execute each fn over fresh symbolic inputs
  │     • collect path constraints + output expressions
  │     • build (inputs equal) ∧ (outputs differ) → Z3 solve      (solver.py)
  │           • UNSAT → EQUIVALENT up to bound N
  │           • SAT   → decode model → COUNTEREXAMPLE
  └─ REPORT (verdict, bound, counterexample, solver stats, caveats)  (report.py)
```

---

## The demo it's built to land

An LLM "simplifies" a midpoint calculation:

```python
# original (correct under fixed-width ints)
def mid(lo: int, hi: int) -> int:
    return lo + (hi - lo) // 2

# candidate (AI "simplification")
def mid(lo: int, hi: int) -> int:
    return (lo + hi) // 2
```

Target behavior:

```console
$ congruent original.py:mid candidate.py:mid --bound 8 --int-width 32
COUNTEREXAMPLE  (stage: symbolic, 0.04s)
  inputs:    lo = 2000000000, hi = 2000000000
  original:  2000000000
  candidate: -147483648        # 32-bit overflow in (lo + hi)
  assumptions: 32-bit two's-complement integers
```

One screenshot of *proof-or-counterexample on a real AI refactor* communicates the whole value.

> **Status: pre-implementation / walking skeleton.** The structure, interfaces, and data model are in place; the engine stages are being built. The output above is the M1 target, not yet wired.

---

## Install

```bash
git clone <repo-url> congruent
cd congruent
python -m pip install -e ".[dev]"
```

Requires Python 3.11+. The solver backend is `z3-solver`.

## Usage

```bash
congruent path/to/original.py:func_name path/to/candidate.py:func_name --bound 8
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `--bound N` | `8` | Loop/recursion unroll depth and array-length bound |
| `--int-width W` | `32` | Bit width for the fixed-width integer model |

## Layout

```
src/congruent/
  ir.py         # AST → normalized typed IR
  difftest.py   # property-based prefilter (Stage 1)
  symbolic.py   # symbolic interpreter → Z3 exprs (Stage 2)
  solver.py     # Z3 abstraction + model decoding
  equiv.py      # orchestration, escalation, Verdict data model
  report.py     # verdict formatting
  cli.py        # `congruent a.py:f b.py:g --bound 8`
tests/
  fixtures/     # equivalent + non-equivalent pairs (the eval set)
  test_equiv.py
benchmarks/     # timing vs bound; recall on known pairs
```

## Roadmap & progress

- [ROADMAP.md](ROADMAP.md) — milestones M0→M4 and the out-of-scope list as future work.

## License

MIT — see [LICENSE](LICENSE).
