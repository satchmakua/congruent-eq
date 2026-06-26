"""Recall benchmark: run Congruent over the fixture eval set.

Tabulates each fixture's verdict against its declared `EXPECTED`. The headline
invariant is **zero unsound verdicts** — no false `EQUIVALENT` (claiming a
broken rewrite is fine) and no false `COUNTEREXAMPLE` (flagging a correct one).

Run it:  python benchmarks/bench_recall.py [--bound N]
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from congruent import check  # noqa: E402
from congruent.ir import parse_function  # noqa: E402

FIXTURES = _REPO / "tests" / "fixtures"


@dataclass
class Result:
    name: str
    expected: str
    status: str
    sound: bool
    solver_time: float | None


def _expected(source: str) -> str:
    """Read the module-level `EXPECTED` constant without executing the fixture."""
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "EXPECTED":
                    return ast.literal_eval(node.value)
    return "?"


def evaluate(bound: int = 8) -> list[Result]:
    results: list[Result] = []
    for path in sorted(FIXTURES.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        expected = _expected(source)
        verdict = check(
            parse_function(source, "original"),
            parse_function(source, "candidate"),
            bound=bound,
        )
        status = verdict.status.value
        unsound = (expected == "EQUIVALENT" and status == "COUNTEREXAMPLE") or (
            expected == "COUNTEREXAMPLE" and status == "EQUIVALENT"
        )
        results.append(Result(path.stem, expected, status, not unsound, verdict.solver_time))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bound", type=int, default=8)
    args = parser.parse_args(argv)

    results = evaluate(args.bound)
    width = max(len(r.name) for r in results)
    print(f"{'fixture':<{width}}  {'expected':<14}  {'verdict':<14}  time")
    print("-" * (width + 38))
    for r in results:
        flag = "" if r.sound else "  <-- UNSOUND"
        mark = "ok" if r.status == r.expected else ("--" if r.sound else "!!")
        t = f"{r.solver_time * 1000:.1f}ms" if r.solver_time is not None else "-"
        print(f"{r.name:<{width}}  {r.expected:<14}  {r.status:<14}  {t:>7}  {mark}{flag}")

    matched = sum(r.status == r.expected for r in results)
    unsound = sum(not r.sound for r in results)
    print("-" * (width + 38))
    print(f"{matched}/{len(results)} verdicts match expectation; {unsound} unsound")
    return 1 if unsound else 0


if __name__ == "__main__":
    raise SystemExit(main())
