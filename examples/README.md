# Gallery

Realistic AI-refactor pairs — the kind of change a coding agent makes when asked
to "optimize" or "clean up" code — with Congruent's verdict on each. Some are
faithful rewrites; some are subtly broken.

Run the whole gallery:

```bash
python examples/run_gallery.py
```

**Closed loop** — `closed_loop_demo.py` puts Congruent in an LLM refactoring
loop: the model proposes a rewrite, Congruent verifies it, and each counterexample
is fed back until the rewrite is *proven* equivalent. Runs offline by default:

```bash
python examples/closed_loop_demo.py          # scripted LLM, deterministic
python examples/closed_loop_demo.py --live   # real Anthropic API (needs the [llm] extra + a key)
python examples/live_rewrite.py FILE.py:func # the same live loop, pointed at your code
```

Captured live sessions (a real model caught proposing the midpoint-overflow bug,
and a ~50-line billing routine rewritten and proven) are in
[docs/live_run.md](../docs/live_run.md).

Or check one pair with the CLI:

```bash
congruent examples/midpoint_overflow.py:original examples/midpoint_overflow.py:candidate --int-width 32
```

Congruent also reads **C** (files ending in `.c`, via `pip install pycparser`):

```bash
congruent examples/midpoint.c:original examples/midpoint.c:candidate --int-width 32
```

| Example | Refactor | Verdict |
| --- | --- | --- |
| [midpoint_overflow.py](midpoint_overflow.py) | `lo + (hi-lo)//2` → `(lo+hi)//2` | **COUNTEREXAMPLE** — overflows at 32 bits |
| [clamp_range.py](clamp_range.py) | nested ifs → one conditional expression | **EQUIVALENT** |
| [list_maximum.py](list_maximum.py) | running max seeded at `0` instead of `xs[0]` | **COUNTEREXAMPLE** — all-negative lists |
| [sum_0_to_n.py](sum_0_to_n.py) | accumulating loop → Gauss closed form | **EQUIVALENT** (for `n >= 0`) |
| [all_positive.py](all_positive.py) | full scan → short-circuit early return | **EQUIVALENT** |
| [has_negative.py](has_negative.py) | full scan → short-circuit with `break` | **EQUIVALENT** |
| [count_positives.py](count_positives.py) | `>` quietly changed to `>=` | **COUNTEREXAMPLE** — lists with a `0` |
| [keep_positives.py](keep_positives.py) | filter rewrite keeps zeros (`>=` vs `>`) | **COUNTEREXAMPLE** — list in, list out |
| [string_greeting.py](string_greeting.py) | greeting with swapped concatenation order | **COUNTEREXAMPLE** — `str` in, `str` out |
| [water_bill.py](water_bill.py) | ~50-line tiered billing, rewritten by a **live model** | **EQUIVALENT** — accepted only after proof |
| [polyval.py](polyval.py) | **numpy's** Horner loop, seed-optimized by a **live model** | **EQUIVALENT** at 8-bit/bound-2 — the solver's hard case (see [live_run.md](../docs/live_run.md)) |

Each module declares `TITLE`, `STORY`, `EXPECTED`, and an `original` / `candidate`
pair; `tests/test_examples.py` pins every verdict so the gallery can't rot.
