# Benchmarks

Two questions this directory answers, reported in the README at M3:

1. **Recall on known pairs** — over the `tests/fixtures/` eval set, how many
   equivalent pairs are confirmed and how many broken pairs are caught (with the
   counterexample). False "EQUIVALENT" verdicts are the cardinal sin; track them.
2. **Cost vs. bound** — wall-clock and solver time as the bound grows, so the
   scaling story is explicit rather than hand-waved.

## Planned

- `bench_recall.py` — run `congruent.check` over every fixture; tabulate
  verdict vs. `EXPECTED`.
- `bench_scaling.py` — sweep `--bound` on a fixed pair; plot time vs. bound.

Nothing here runs yet — it lands with M3 once the engine (M1) exists.
