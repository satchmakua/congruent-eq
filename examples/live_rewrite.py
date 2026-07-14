"""Point the closed loop at any function in any file: a real model proposes a
rewrite, Congruent verifies it, and counterexamples feed back until the rewrite
is proven equivalent — or the round budget runs out.

    python examples/live_rewrite.py examples/water_bill.py:original
    python examples/live_rewrite.py mycode.py:parse_flags --goal "use one loop"

This is the general-purpose version of closed_loop_demo.py: same loop, your
code. Needs `pip install "congruent[llm]"` and `ANTHROPIC_API_KEY`.
"""

from __future__ import annotations

import argparse
import ast
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from congruent.refine import DEFAULT_MODEL, AnthropicRewriter, RewriteTask, refine  # noqa: E402
from congruent.report import format_verdict  # noqa: E402

# The default goal spells out the checkable subset, the way any real integration
# would: there is no point letting the model propose code the verifier must
# refuse. (If it strays anyway, the parse error is fed back and the loop goes on.)
_DEFAULT_GOAL = (
    "rewrite the function to be shorter and clearer while preserving behavior "
    "exactly. Stay within this Python subset: int/bool/list[int]/str parameters; "
    "if/elif/else and ternaries; `for ... in range(...)` and `for x in xs` loops "
    "with break/continue; assignment to plain names only; + - * // %; comparisons; "
    "and/or/not; len(); list literals and list +; subscript reads. No other calls "
    "or builtins, no while, no comprehensions, no del, no element assignment; "
    "initialize any loop-carried temporary before its loop"
)


def _extract_function(path: Path, name: str) -> str:
    source = path.read_text(encoding="utf-8")
    module = ast.parse(source)
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            segment = ast.get_source_segment(source, node)
            if segment is not None:
                return segment
    raise SystemExit(f"error: no function named {name!r} in {path}")


class _TimedRewriter:
    """Wrap a rewriter to record each call's wall-clock (the model latency)."""

    def __init__(self, inner: AnthropicRewriter) -> None:
        self._inner = inner
        self.llm_seconds: list[float] = []

    def __call__(self, task: RewriteTask) -> str:
        start = time.perf_counter()
        out = self._inner(task)
        self.llm_seconds.append(time.perf_counter() - start)
        return out


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to a legacy code page (e.g. cp1252); force UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="FILE.py:function_name")
    parser.add_argument("--goal", default=_DEFAULT_GOAL)
    parser.add_argument("--bound", type=int, default=8)
    parser.add_argument("--int-width", type=int, default=32)
    parser.add_argument("--max-rounds", type=int, default=4)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout", type=float, default=60.0,
                        help="per-request API timeout in seconds (default 60)")
    parser.add_argument("--max-retries", type=int, default=1,
                        help="API retries per request (default 1; a timeout multiplies across these)")
    parser.add_argument("--check-timeout-ms", type=int, default=20_000,
                        help="per-verification Z3 timeout in ms, so a hard query is UNKNOWN not a hang")
    args = parser.parse_args(argv)

    file_part, sep, name = args.target.partition(":")
    if not sep or not name:
        parser.error("target must look like path/to/file.py:function_name")
    original_source = _extract_function(Path(file_part), name)

    print(f"Live rewrite of {args.target}")
    print(f"model: {args.model}   bound: {args.bound}   ints: {args.int_width}-bit")
    print(f"goal: {args.goal}")
    print()
    print("original:")
    for line in original_source.strip().splitlines():
        print(f"    {line}")
    print()

    rewriter = _TimedRewriter(
        AnthropicRewriter(model=args.model, timeout=args.timeout, max_retries=args.max_retries)
    )
    started = time.perf_counter()
    result = refine(
        original_source, name, rewriter,
        goal=args.goal, max_rounds=args.max_rounds,
        bound=args.bound, int_width=args.int_width, timeout_ms=args.check_timeout_ms,
    )
    total = time.perf_counter() - started

    for i, rnd in enumerate(result.rounds):
        llm = rewriter.llm_seconds[i] if i < len(rewriter.llm_seconds) else 0.0
        print(f"── round {i + 1}  (model latency: {llm:.1f}s) ──")
        print("  candidate:")
        for line in rnd.candidate_source.strip().splitlines():
            print(f"      {line}")
        print("  verdict:")
        for line in format_verdict(rnd.verdict).splitlines():
            print(f"    {line}")
        print()

    if result.verified:
        print(f"VERIFIED in {len(result.rounds)} round(s), {total:.1f}s wall-clock "
              f"(model + verification). The loop only accepts a proven rewrite.")
    else:
        print(f"NOT verified after {len(result.rounds)} round(s), {total:.1f}s "
              f"wall-clock (final status: {result.status.name}).")
    return 0 if result.verified else 1


if __name__ == "__main__":
    raise SystemExit(main())
