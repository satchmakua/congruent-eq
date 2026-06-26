"""Solver abstraction: build the equivalence query, solve, decode the model.

Given two `FunctionSummary` objects, assert that the functions receive *equal
inputs* yet produce *different outputs*, and ask the solver:

    UNSAT -> no diverging input exists within the bound -> EQUIVALENT
    SAT   -> the model IS a counterexample -> decode back to concrete inputs

Z3 is the v1 backend. Everything solver-specific is funneled through this
module so a CVC5 (or other) backend can slot in behind the same interface
later (ROADMAP.md M4).
"""

from __future__ import annotations

from congruent.equiv import Counterexample, Verdict
from congruent.symbolic import FunctionSummary


def prove_equivalence(
    original: FunctionSummary,
    candidate: FunctionSummary,
    *,
    bound: int,
    assumptions: list[str] | None = None,
) -> Verdict:
    """Build and solve the equivalence query for two function summaries.

    Args:
        original: symbolic summary of the reference function.
        candidate: symbolic summary of the rewritten function.
        bound: the bound this verdict holds up to (recorded on the result).
        assumptions: human-readable caveats to attach (e.g. integer width).

    Returns:
        A `Verdict`:
            - `EQUIVALENT`     when the query is UNSAT,
            - `COUNTEREXAMPLE` when SAT (model decoded via `_decode_model`),
            - `UNKNOWN`        when the solver times out or returns unknown.
    """
    # TODO(M1): equate inputs; assert outputs differ across path pairs.
    # TODO(M1): solver.check(); on sat -> _decode_model; on unsat -> EQUIVALENT.
    raise NotImplementedError("solver query not yet implemented — see ROADMAP.md (M1)")


def _decode_model(model: object, inputs: dict[str, object]) -> Counterexample:
    """Turn a satisfying Z3 model into a concrete `Counterexample`.

    Reads each input symbol's value out of the model and converts it back to a
    plain Python value (bitvector -> signed int, etc.).
    """
    # TODO(M1): evaluate each input symbol in the model -> Python value.
    raise NotImplementedError("model decoding not yet implemented — see ROADMAP.md (M1)")
