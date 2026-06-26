# Gallery

Realistic AI-refactor pairs — the kind of change a coding agent makes when asked
to "optimize" or "clean up" code — with Congruent's verdict on each. Some are
faithful rewrites; some are subtly broken.

Run the whole gallery:

```bash
python examples/run_gallery.py
```

Or check one pair with the CLI:

```bash
congruent examples/midpoint_overflow.py:original examples/midpoint_overflow.py:candidate --int-width 32
```

| Example | Refactor | Verdict |
| --- | --- | --- |
| [midpoint_overflow.py](midpoint_overflow.py) | `lo + (hi-lo)//2` → `(lo+hi)//2` | **COUNTEREXAMPLE** — overflows at 32 bits |
| [clamp_range.py](clamp_range.py) | nested ifs → one conditional expression | **EQUIVALENT** |
| [list_maximum.py](list_maximum.py) | running max seeded at `0` instead of `xs[0]` | **COUNTEREXAMPLE** — all-negative lists |
| [sum_0_to_n.py](sum_0_to_n.py) | accumulating loop → Gauss closed form | **EQUIVALENT** (for `n >= 0`) |
| [all_positive.py](all_positive.py) | full scan → short-circuit early return | **EQUIVALENT** |
| [count_positives.py](count_positives.py) | `>` quietly changed to `>=` | **COUNTEREXAMPLE** — lists with a `0` |
| [keep_positives.py](keep_positives.py) | filter rewrite keeps zeros (`>=` vs `>`) | **COUNTEREXAMPLE** — list in, list out |

Each module declares `TITLE`, `STORY`, `EXPECTED`, and an `original` / `candidate`
pair; `tests/test_examples.py` pins every verdict so the gallery can't rot.
