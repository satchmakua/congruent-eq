"""The closed-loop demo: an LLM proposes a rewrite, Congruent verifies it, and
each counterexample is fed back until the rewrite is *proven* equivalent.

By default this runs fully offline with a `ScriptedRewriter` that replays what an
LLM typically does — a plausible-but-buggy first attempt, then a fix once
Congruent hands back the exact failing input. Pass `--live` to drive a real model
through the Anthropic API instead (needs `pip install "congruent[llm]"` and a key).

    python examples/closed_loop_demo.py            # offline, deterministic
    python examples/closed_loop_demo.py --live     # real LLM in the loop
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from congruent.equiv import Status  # noqa: E402
from congruent.refine import AnthropicRewriter, RefineResult, ScriptedRewriter, refine  # noqa: E402


@dataclass
class Scenario:
    title: str
    story: str
    name: str
    goal: str
    original: str
    scripted_attempts: list[str]  # what the offline stand-in LLM "proposes"
    check_kwargs: dict


SCENARIOS = [
    Scenario(
        title="Loop → closed form",
        story=(
            "A coding agent is asked to replace an accumulating loop with a closed "
            "form. Its first try drops the +1, so it is wrong for every n. Congruent "
            "hands back the smallest failing input; the second try is correct."
        ),
        name="total",
        goal="replace the loop with an equivalent closed-form expression",
        original=(
            "def total(n: int) -> int:\n"
            "    assume(n >= 0)\n"
            "    s = 0\n"
            "    for i in range(n + 1):\n"
            "        s = s + i\n"
            "    return s"
        ),
        scripted_attempts=[
            "def total(n: int) -> int:\n    return n * n // 2",         # buggy
            "def total(n: int) -> int:\n    return n * (n + 1) // 2",   # correct
        ],
        check_kwargs={"bound": 8, "int_width": 32},
    ),
    Scenario(
        title="Binary-search midpoint (the classic overflow trap)",
        story=(
            "The original computes a midpoint the overflow-safe way. The agent "
            "'simplifies' it to (a + b) // 2 — the classic bug that overflows for "
            "large inputs. Congruent catches it at the exact boundary and the agent "
            "reverts to the safe form."
        ),
        name="mid",
        goal="simplify the midpoint computation",
        original="def mid(a: int, b: int) -> int:\n    return a + (b - a) // 2",
        scripted_attempts=[
            "def mid(a: int, b: int) -> int:\n    return (a + b) // 2",       # overflow bug
            "def mid(a: int, b: int) -> int:\n    return a + (b - a) // 2",   # safe
        ],
        check_kwargs={"bound": 4, "int_width": 8},
    ),
]


def _print_source(label: str, src: str) -> None:
    print(f"  {label}")
    for line in src.strip().splitlines():
        print(f"      {line}")


def _run(scenario: Scenario, live: bool) -> RefineResult:
    if live:
        rewriter = AnthropicRewriter()
        # The scripted story narrates the canned attempts; a live model chooses
        # its own, so narrate only what is actually promised: the loop.
        story = (
            f"A real model ({rewriter.model}) is asked to {scenario.goal}. "
            f"Congruent verifies each attempt; any counterexample is fed back "
            f"until a rewrite is proven equivalent."
        )
    else:
        rewriter = ScriptedRewriter(scenario.scripted_attempts)
        story = scenario.story

    print("=" * 78)
    print(scenario.title)
    print("-" * 78)
    print(story)
    print()
    _print_source("original:", scenario.original)
    print()

    result = refine(
        scenario.original, scenario.name, rewriter, goal=scenario.goal, **scenario.check_kwargs
    )

    for i, rnd in enumerate(result.rounds):
        print(f"  ── round {i + 1}: the LLM proposes ──")
        _print_source("candidate:", rnd.candidate_source)
        v = rnd.verdict
        if v.status is Status.EQUIVALENT:
            note = v.assumptions[-1] if v.assumptions else ""
            print(f"    ✓ Congruent: EQUIVALENT — proven ({note})")
        elif v.status is Status.COUNTEREXAMPLE and v.counterexample is not None:
            cx = v.counterexample
            args = ", ".join(f"{k}={val!r}" for k, val in cx.inputs.items())
            print(f"    ✗ Congruent: COUNTEREXAMPLE at {args} "
                  f"→ original={cx.original_output!r}, rewrite={cx.candidate_output!r}")
            print("      (fed back to the LLM for the next round)")
        else:
            print(f"    · Congruent: {v.status.name}")
        print()

    if result.verified:
        print(f"  RESULT: verified equivalent in {len(result.rounds)} round(s). "
              f"The loop only accepts a *proven* rewrite.")
    else:
        print(f"  RESULT: not verified after {len(result.rounds)} round(s) "
              f"(final: {result.status.name}).")
    print()
    return result


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to a legacy code page (e.g. cp1252) that cannot
    # encode the arrows/check marks below; force UTF-8 with a safe fallback.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true",
                        help="use the real Anthropic API instead of the scripted LLM")
    args = parser.parse_args(argv)

    mode = "LIVE (Anthropic API)" if args.live else "offline (scripted LLM)"
    print("Congruent closed loop — AI proposes, Congruent verifies, counterexamples feed back.")
    print(f"Mode: {mode}\n")

    results = [_run(s, args.live) for s in SCENARIOS]
    verified = sum(r.verified for r in results)
    print("=" * 78)
    print(f"{verified}/{len(results)} rewrites proven equivalent through the loop.")
    return 0 if verified == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
