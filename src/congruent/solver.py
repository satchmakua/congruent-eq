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
    inputs, well_formed = symbolic.make_inputs(original.params, int_width, bound)
    summary_o = symbolic.summarize(original, inputs, int_width, bound)
    summary_c = symbolic.summarize(candidate, inputs, int_width, bound)

    solver = z3.Solver()
    # Inputs must be well-formed (e.g. list lengths within [0, bound])...
    for constraint in well_formed:
        solver.add(constraint)
    # ...satisfy the declared preconditions...
    for precond in (
        symbolic.lower_preconditions(original, inputs, int_width)
        + symbolic.lower_preconditions(candidate, inputs, int_width)
    ):
        solver.add(precond)
    # ...and keep every loop within the bound.
    for assumption in summary_o.assumptions + summary_c.assumptions:
        solver.add(assumption)

    # Functions differ if their runtime-error behavior differs, or if both
    # complete normally but produce different outputs.
    both_ok = z3.And(z3.Not(summary_o.error), z3.Not(summary_c.error))
    solver.add(
        z3.Or(
            summary_o.error != summary_c.error,
            z3.And(both_ok, _differ(summary_o.output, summary_c.output, int_width)),
        )
    )

    start = time.perf_counter()
    result = solver.check()
    elapsed = time.perf_counter() - start

    unrolled = summary_o.unrolled or summary_c.unrolled
    has_list = any(p.type_name == "list[int]" for p in original.params)

    if result == z3.unsat:
        bounded_bits = []
        if has_list:
            bounded_bits.append(f"lists up to length {bound}")
        if unrolled:
            bounded_bits.append(f"loops up to {bound} iterations")
        if bounded_bits:
            scope_note = "holds within bound: " + ", ".join(bounded_bits)
        elif original.preconditions or candidate.preconditions:
            # Loop-free but constrained: complete over the precondition's domain.
            scope_note = f"complete: agree on all {int_width}-bit inputs satisfying the precondition"
        else:
            # Loop-free and unconstrained: the summary is exact for every input.
            scope_note = f"complete: agree on all {int_width}-bit inputs (no loops to bound)"
        return Verdict(
            status=Status.EQUIVALENT,
            bound=bound,
            solver_time=elapsed,
            stage="symbolic",
            assumptions=assumptions + [scope_note],
        )

    if result == z3.sat:
        model = solver.model()
        cx = _decode_model(model, inputs, original.params, summary_o, summary_c, int_width, bound)
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
    inputs: list,
    params: list,
    summary_original: "symbolic.Summary",
    summary_candidate: "symbolic.Summary",
    int_width: int,
    bound: int,
) -> Counterexample:
    """Turn a satisfying model into a concrete `Counterexample`."""
    concrete: dict[str, object] = {}
    for param, value in zip(params, inputs):
        if isinstance(value, symbolic.SymList):
            length = int(_to_py(model.eval(value.length, model_completion=True)))
            length = max(0, min(length, bound))
            concrete[param.name] = [
                _to_py(model.eval(z3.Select(value.arr, z3.BitVecVal(i, int_width)), model_completion=True))
                for i in range(length)
            ]
        else:
            concrete[param.name] = _to_py(model.eval(value, model_completion=True))
    return Counterexample(
        inputs=concrete,
        original_output=_decode_output(model, summary_original),
        candidate_output=_decode_output(model, summary_candidate),
    )


def _decode_output(model: z3.ModelRef, summary: "symbolic.Summary") -> object:
    """A function's observable result in the model: a value, or a raised error."""
    if z3.is_true(model.eval(summary.error, model_completion=True)):
        return "<raises>"
    return _to_py(model.eval(summary.output, model_completion=True))


def _to_py(value: z3.ExprRef) -> object:
    if z3.is_bool(value):
        return z3.is_true(value)
    if z3.is_bv_value(value):
        return value.as_signed_long()
    return value  # pragma: no cover — unexpected sort, surface it as-is
