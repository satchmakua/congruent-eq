"""Solver layer: build the equivalence query, solve, decode the model.

Summarize both functions over the *same* fresh symbolic inputs, then ask Z3
whether their outputs can differ:

    UNSAT -> no diverging input exists within the model -> EQUIVALENT
    SAT   -> the model IS a counterexample -> decode back to concrete inputs
    unknown -> solver gave up -> UNKNOWN

Z3 is the v1 backend; everything solver-specific lives here so a different
backend can slot in behind `prove_equivalence` later (ROADMAP.md M4).
"""

from __future__ import annotations

import time

import z3

from congruent import symbolic
from congruent.equiv import Counterexample, Status, Verdict
from congruent.ir import Function


def prove_equivalence(
    original: Function,
    candidate: Function,
    *,
    bound: int,
    int_width: int,
    assumptions: list[str],
) -> Verdict:
    """Run the symbolic equivalence query for two (signature-matched) functions.

    Raises:
        symbolic.UnsupportedForProof: a function uses something the symbolic
            stage cannot soundly model; the caller should fall back to the
            differential verdict rather than guess.
    """
    inputs = symbolic.make_input_symbols(original.params, int_width)
    out_original = symbolic.summarize(original, inputs, int_width)
    out_candidate = symbolic.summarize(candidate, inputs, int_width)

    solver = z3.Solver()
    solver.add(_differ(out_original, out_candidate, int_width))

    start = time.perf_counter()
    result = solver.check()
    elapsed = time.perf_counter() - start

    if result == z3.unsat:
        # The M1 subset is loop-free, so the summary is exact: UNSAT means the
        # outputs agree on *every* input at this width, not just within a bound.
        return Verdict(
            status=Status.EQUIVALENT,
            bound=bound,
            solver_time=elapsed,
            stage="symbolic",
            assumptions=assumptions + [f"complete: agree on all {int_width}-bit inputs (no loops to bound)"],
        )

    if result == z3.sat:
        model = solver.model()
        cx = _decode_model(model, inputs, original.params, out_original, out_candidate)
        return Verdict(
            status=Status.COUNTEREXAMPLE,
            bound=bound,
            counterexample=cx,
            solver_time=elapsed,
            stage="symbolic",
            assumptions=assumptions,
        )

    return Verdict(
        status=Status.UNKNOWN,
        bound=bound,
        solver_time=elapsed,
        stage="symbolic",
        assumptions=assumptions + [f"solver returned unknown: {solver.reason_unknown()}"],
    )


def _differ(a: z3.ExprRef, b: z3.ExprRef, int_width: int) -> z3.ExprRef:
    """Assertion that the two outputs disagree, coercing to a common sort."""
    if z3.is_bool(a) and z3.is_bool(b):
        return a != b
    return symbolic._as_bv(a, int_width) != symbolic._as_bv(b, int_width)


def _decode_model(
    model: z3.ModelRef,
    inputs: list[z3.ExprRef],
    params: list,
    out_original: z3.ExprRef,
    out_candidate: z3.ExprRef,
) -> Counterexample:
    """Turn a satisfying model into a concrete `Counterexample`."""
    concrete = {
        param.name: _to_py(model.eval(sym, model_completion=True))
        for param, sym in zip(params, inputs)
    }
    return Counterexample(
        inputs=concrete,
        original_output=_to_py(model.eval(out_original, model_completion=True)),
        candidate_output=_to_py(model.eval(out_candidate, model_completion=True)),
    )


def _to_py(value: z3.ExprRef) -> object:
    if z3.is_bool(value):
        return z3.is_true(value)
    if z3.is_bv_value(value):
        return value.as_signed_long()
    return value  # pragma: no cover — unexpected sort, surface it as-is
