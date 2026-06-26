"""Command-line entry point.

    congruent path/to/original.py:func  path/to/candidate.py:func  --bound 8

Parses two ``file.py:function`` specs plus bound config, runs the equivalence
pipeline, and prints the formatted verdict. Exit codes:

    0  EQUIVALENT
    1  COUNTEREXAMPLE
    2  UNKNOWN / ERROR / engine not yet implemented
"""

from __future__ import annotations

import argparse
import sys

from congruent.equiv import Status, check
from congruent.report import format_verdict


def _parse_spec(spec: str) -> tuple[str, str]:
    """Split a ``path/to/file.py:function`` spec into (path, function name)."""
    path, sep, func = spec.rpartition(":")
    # rpartition on Windows: keep drive letters intact (only split the last ':').
    if not sep or not path or not func:
        raise argparse.ArgumentTypeError(
            f"expected 'file.py:function', got {spec!r}"
        )
    return path, func


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="congruent",
        description="Prove behavioral equivalence of two functions within bounds, "
        "or return the concrete input that breaks it.",
    )
    parser.add_argument("original", type=_parse_spec, help="original spec, e.g. a.py:f")
    parser.add_argument("candidate", type=_parse_spec, help="candidate spec, e.g. b.py:g")
    parser.add_argument(
        "--bound", type=int, default=8,
        help="loop/recursion unroll depth and array-length bound (default: 8)",
    )
    parser.add_argument(
        "--int-width", type=int, default=32,
        help="bit width for the fixed-width integer model (default: 32)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    (orig_path, orig_fn) = args.original
    (cand_path, cand_fn) = args.candidate

    # TODO(M0): parse both files to IR via ir.parse_function, then pass to check().
    try:
        verdict = check(
            (orig_path, orig_fn),
            (cand_path, cand_fn),
            bound=args.bound,
            int_width=args.int_width,
        )
    except NotImplementedError as exc:
        print(f"congruent: not yet implemented: {exc}", file=sys.stderr)
        return 2

    print(format_verdict(verdict))
    return {
        Status.EQUIVALENT: 0,
        Status.COUNTEREXAMPLE: 1,
    }.get(verdict.status, 2)


if __name__ == "__main__":
    raise SystemExit(main())
