"""Orchestration, escalation logic, and the verdict data model.

This module owns the `Verdict` result type and the top-level `check()` entry
point. `check()` runs the layered pipeline, escalating from cheap to expensive:

    Stage 1  differential testing  (difftest.py)  — milliseconds        [M0]
    Stage 2  symbolic execution    (symbolic.py)  — SMT solve via solver [M1]

A counterexample at any stage short-circuits and is returned immediately.
Reaching `UNSAT` in the symbolic stage yields `EQUIVALENT up to bound N`.

At M0 only Stage 1 exists, so the possible verdicts are COUNTEREXAMPLE (a
disagreement was found), UNKNOWN (none found — NOT a proof of equivalence), or
ERROR (e.g. mismatched signatures). EQUIVALENT arrives with Stage 2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from congruent.ir import Function


class Status(str, Enum):
    """Terminal verdict for an equivalence query."""

    EQUIVALENT = "EQUIVALENT"          # no diverging input exists within the bound
    COUNTEREXAMPLE = "COUNTEREXAMPLE"  # a concrete diverging input was found
    UNKNOWN = "UNKNOWN"               # solver timed out / gave up within the bound
    ERROR = "ERROR"                   # parse error, unsupported construct, etc.


@dataclass
class Counterexample:
    """A concrete input on which the two functions disagree."""

    inputs: dict[str, object]
    original_output: object
    candidate_output: object


@dataclass
class Verdict:
    """The result of an equivalence query.

    Every verdict carries the `bound` it holds up to and any `assumptions`
    (e.g. the integer width) so a result is never read out of context.
    """

    status: Status
    bound: int
    counterexample: Counterexample | None = None
    solver_time: float | None = None
    stage: str | None = None          # which stage decided: "difftest" | "symbolic"
    assumptions: list[str] = field(default_factory=list)


def check(
    original: Function,
    candidate: Function,
    *,
    bound: int = 8,
    int_width: int = 32,
    trials: int = 2000,
    seed: int = 0,
    minimize: bool = True,
) -> Verdict:
    """Decide behavioral equivalence of two functions up to `bound`.

    Args:
        original: the reference function IR (see `ir.parse_function`).
        candidate: the rewritten function IR to compare against the reference.
        bound: loop/recursion unroll depth and array-length bound.
        int_width: bit width for the fixed-width integer model.
        trials: random inputs to sample in the differential stage.
        seed: RNG seed, so a verdict is reproducible.

    Returns:
        A `Verdict`. `COUNTEREXAMPLE` carries a concrete diverging input;
        `UNKNOWN` means difftest found nothing (NOT a proof — Stage 2 lands in
        M1); `ERROR` covers e.g. mismatched signatures.
    """
    from congruent.difftest import find_counterexample  # local import avoids a cycle

    assumptions = [f"{int_width}-bit two's-complement integers"]
    precond_texts: list[str] = []
    for pc in (*original.preconditions, *candidate.preconditions):
        if pc.text not in precond_texts:  # dedupe (both functions may declare it)
            precond_texts.append(pc.text)
    if precond_texts:
        assumptions.append("precondition: " + " and ".join(precond_texts))

    orig_types = [p.type_name for p in original.params]
    cand_types = [p.type_name for p in candidate.params]
    if orig_types != cand_types:
        return Verdict(
            status=Status.ERROR,
            bound=bound,
            stage="parse",
            assumptions=[f"signatures differ: original {orig_types} vs candidate {cand_types}"],
        )

    def unknown(reason: str) -> Verdict:
        note = "no counterexample found by differential testing; equivalence not proven"
        return Verdict(
            status=Status.UNKNOWN, bound=bound, stage="difftest",
            assumptions=assumptions + [f"{note} ({reason})"],
        )

    # Stage 1 — differential testing (cheap; boundary witnesses are already minimal).
    cx = find_counterexample(
        original, candidate, bound=bound, int_width=int_width, trials=trials, seed=seed
    )
    if cx is not None:
        return Verdict(
            status=Status.COUNTEREXAMPLE, bound=bound, counterexample=cx,
            stage="difftest", assumptions=assumptions,
        )

    # Stage 2 — symbolic execution + SMT: proves EQUIVALENT (UNSAT) or yields a
    # *minimized* COUNTEREXAMPLE. If it can't soundly model the functions, fall
    # back to honest UNKNOWN rather than risk a false proof.
    try:
        from congruent.solver import prove_equivalence
        from congruent.symbolic import UnsupportedForProof
    except ImportError:
        return unknown("z3 not installed; symbolic stage skipped")

    try:
        return prove_equivalence(
            original, candidate,
            bound=bound, int_width=int_width, assumptions=assumptions, minimize=minimize,
        )
    except UnsupportedForProof as exc:
        return unknown(f"symbolic stage declined: {exc}")
