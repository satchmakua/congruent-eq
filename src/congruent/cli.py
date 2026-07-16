"""Command-line entry point.

    congruent path/to/original.py:func  path/to/candidate.py:func  --bound 8

Parses two ``file.py:function`` specs plus bound config, runs the equivalence
pipeline, and prints the formatted verdict. Exit codes:

    0  EQUIVALENT
    1  COUNTEREXAMPLE
    2  UNKNOWN / ERROR
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from congruent.equiv import Status, check
from congruent.ir import UnsupportedConstruct, parse_condition, parse_function
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
        help="loop unroll depth and list/string-length bound (default: 8)",
    )
    parser.add_argument(
        "--int-width", type=int, default=32,
        help="bit width for the fixed-width integer model (default: 32)",
    )
    parser.add_argument(
        "--assume", action="append", metavar="EXPR", default=[],
        help="precondition on the inputs, e.g. --assume 'n >= 0' (repeatable)",
    )
    parser.add_argument(
        "--no-minimize", dest="minimize", action="store_false",
        help="report the first counterexample found, not the smallest",
    )
    parser.add_argument(
        "--cross-check", action="store_true",
        help="independently re-decide with CVC5 and flag any disagreement",
    )
    parser.add_argument(
        "--timeout", type=float, default=300.0, metavar="SECONDS",
        help="give up on the solver after SECONDS and report UNKNOWN (default: 300; "
             "0 = no limit). Some queries — e.g. multiplying unknowns by unknowns in a "
             "loop — are intractable and would otherwise run forever",
    )
    return parser


def _parse_file(path: str, name: str):
    """Parse a function from a file, picking the front end by extension (.c = C)."""
    source = Path(path).read_text(encoding="utf-8")
    if path.endswith(".c"):
        from congruent.cfront import parse_c_function
        return parse_c_function(source, name)
    return parse_function(source, name)


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to a legacy code page (e.g. cp1252). A string
    # counterexample can decode to *any* code point (see solver._decode_seq), so
    # without this a perfectly good verdict dies with UnicodeEncodeError instead
    # of being printed.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = build_parser()
    args = parser.parse_args(argv)

    (orig_path, orig_name) = args.original
    (cand_path, cand_name) = args.candidate

    try:
        original = _parse_file(orig_path, orig_name)
        candidate = _parse_file(cand_path, cand_name)
        original.preconditions += tuple(parse_condition(a) for a in args.assume)
    except FileNotFoundError as exc:
        print(f"congruent: file not found: {exc.filename}", file=sys.stderr)
        return 2
    except (UnsupportedConstruct, ValueError, SyntaxError) as exc:
        print(f"congruent: cannot parse input: {exc}", file=sys.stderr)
        return 2

    verdict = check(
        original, candidate, bound=args.bound, int_width=args.int_width,
        minimize=args.minimize, cross_check=args.cross_check,
        timeout_ms=int(args.timeout * 1000) if args.timeout > 0 else None,
    )
    print(format_verdict(verdict))
    return {
        Status.EQUIVALENT: 0,
        Status.COUNTEREXAMPLE: 1,
    }.get(verdict.status, 2)


if __name__ == "__main__":
    raise SystemExit(main())
