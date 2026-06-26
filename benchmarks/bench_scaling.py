"""Scaling benchmark: solver time vs. the unroll/length bound.

Picks fixtures with loops or arrays (where the bound actually drives work) and
times the symbolic stage as the bound grows. Makes the cost-vs-bound story
explicit rather than hand-waved.

Run it:  python benchmarks/bench_scaling.py [--bounds 2,4,8,16,32]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from congruent import check  # noqa: E402
from congruent.ir import parse_function  # noqa: E402

FIXTURES = _REPO / "tests" / "fixtures"

# Fixtures whose cost depends on the bound (loops / arrays), and prove EQUIVALENT.
_TARGETS = ["loop_reorder", "sum_to_n", "array_len_count", "array_sum_reorder"]


def _time_check(name: str, bound: int) -> tuple[str, float]:
    source = (FIXTURES / f"{name}.py").read_text(encoding="utf-8")
    original = parse_function(source, "original")
    candidate = parse_function(source, "candidate")
    start = time.perf_counter()
    verdict = check(original, candidate, bound=bound)
    return verdict.status.value, time.perf_counter() - start


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bounds", default="2,4,8,16,32")
    args = parser.parse_args(argv)
    bounds = [int(b) for b in args.bounds.split(",")]

    width = max(len(t) for t in _TARGETS)
    header = f"{'fixture':<{width}}  " + "  ".join(f"b={b:>3}" for b in bounds)
    print(header)
    print("-" * len(header))
    for name in _TARGETS:
        cells = []
        for bound in bounds:
            status, elapsed = _time_check(name, bound)
            cell = f"{elapsed * 1000:6.1f}ms" if status == "EQUIVALENT" else f"{status[:6]:>8}"
            cells.append(cell)
        print(f"{name:<{width}}  " + "  ".join(cells))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
