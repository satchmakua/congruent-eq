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

Still planned for M3: a curated gallery of real AI-refactor pairs and a README
demo image.
