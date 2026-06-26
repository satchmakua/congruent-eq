"""Orchestration, escalation logic, and the verdict data model.

This module owns the `Verdict` result type and the top-level `check()` entry
point. `check()` runs the layered pipeline, escalating from cheap to expensive:

    Stage 1  differential testing  (difftest.py)  — milliseconds
    Stage 2  symbolic execution    (symbolic.py)  — SMT solve via solver.py

A counterexample at any stage short-circuits and is returned immediately.
Reaching `UNSAT` in the symbolic stage yields `EQUIVALENT up to bound N`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


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
    original: object,
    candidate: object,
    *,
    bound: int = 8,
    int_width: int = 32,
) -> Verdict:
    """Decide behavioral equivalence of two functions up to `bound`.

    Args:
        original: the reference function (parsed IR or callable — TBD in M0).
        candidate: the rewritten function to compare against the reference.
        bound: loop/recursion unroll depth and array-length bound.
        int_width: bit width for the fixed-width integer model.

    Returns:
        A `Verdict`. `EQUIVALENT` is always qualified by `bound` and
        `assumptions`; `COUNTEREXAMPLE` carries a concrete diverging input.

    Pipeline (to be wired in M0/M1):
        1. difftest.find_counterexample(...) -> Counterexample | None
        2. symbolic + solver -> UNSAT (EQUIVALENT) | SAT (COUNTEREXAMPLE)
    """
    # TODO(M0): run difftest prefilter; return COUNTEREXAMPLE on a hit.
    # TODO(M1): build symbolic constraints, solve, decode model.
    raise NotImplementedError(
        "equivalence engine not yet implemented — see ROADMAP.md (M0/M1)"
    )
