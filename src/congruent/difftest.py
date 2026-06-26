"""Differential testing — Stage 1, the cheap prefilter.

Throw random and boundary inputs at both functions and compare outputs. This
catches obvious non-equivalence in milliseconds, before paying for the solver.
A counterexample here short-circuits the whole pipeline.

Inputs are generated from the IR's typed signature (Hypothesis-style), with
explicit boundary values mixed in (0, +/-1, and the min/max of the integer
width) because the interesting bugs cluster at the edges.
"""

from __future__ import annotations

from congruent.equiv import Counterexample
from congruent.ir import Function


def find_counterexample(
    original: Function,
    candidate: Function,
    *,
    bound: int = 8,
    int_width: int = 32,
    trials: int = 1000,
) -> Counterexample | None:
    """Search for a concrete input on which `original` and `candidate` differ.

    Args:
        original: reference function IR.
        candidate: rewritten function IR.
        bound: max length for generated arrays/lists.
        int_width: bit width bounding generated integers (also fixes the
            boundary values, e.g. min/max of two's-complement at this width).
        trials: number of random inputs to try (boundary inputs are extra).

    Returns:
        A `Counterexample` on the first disagreement, else `None`. `None` means
        "no disagreement found by sampling" — NOT a proof of equivalence; that
        only comes from the symbolic stage.
    """
    # TODO(M0): build typed generators from `original.params`.
    # TODO(M0): enumerate boundary inputs, then sample `trials` random inputs.
    # TODO(M0): evaluate both fns per input; return first mismatch.
    raise NotImplementedError("differential tester not yet implemented — see ROADMAP.md (M0)")
