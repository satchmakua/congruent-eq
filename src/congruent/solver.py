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
    minimize: bool = True,
) -> Verdict:
    """Run the symbolic equivalence query for two (signature-matched) functions.

    `UNSAT → EQUIVALENT`, `SAT → COUNTEREXAMPLE` (minimized when `minimize`),
    else `UNKNOWN`.

    Raises:
        symbolic.UnsupportedForProof: a function uses something the symbolic
            stage cannot soundly model; the caller should fall back to the
            differential verdict rather than guess.
    """
    inputs, constraints, summary_o, summary_c = _equivalence_query(
        original, candidate, int_width, bound
    )

    # Decide sat/unsat first with a plain solver (cheaper than Optimize).
    solver = z3.Solver()
    solver.add(*constraints)

    start = time.perf_counter()
    result = solver.check()

    if result == z3.unsat:
        elapsed = time.perf_counter() - start
        return Verdict(
            status=Status.EQUIVALENT,
            bound=bound,
            solver_time=elapsed,
            stage="symbolic",
            assumptions=assumptions + [_scope_note(original, candidate, summary_o, summary_c, int_width, bound)],
        )

    if result == z3.unknown:
        elapsed = time.perf_counter() - start
        return Verdict(
            status=Status.UNKNOWN,
            bound=bound,
            solver_time=elapsed,
            stage="symbolic",
            assumptions=assumptions + [f"solver returned unknown: {solver.reason_unknown()}"],
        )

    # SAT — a counterexample exists. Optionally shrink it to the smallest input.
    model = solver.model()
    notes = list(assumptions)
    if minimize:
        minimal = _minimize(constraints, inputs, int_width)
        if minimal is not None:
            model = minimal
            notes.append("counterexample minimized")
    elapsed = time.perf_counter() - start

    cx = _decode_model(model, inputs, original.params, summary_o, summary_c, int_width, bound)
    return Verdict(
        status=Status.COUNTEREXAMPLE,
        bound=bound,
        counterexample=cx,
        solver_time=elapsed,
        stage="symbolic",
        assumptions=notes,
    )


def _equivalence_query(original, candidate, int_width, bound):
    """Build the shared inputs, the constraint list, and both summaries."""
    inputs, well_formed = symbolic.make_inputs(original.params, int_width, bound)
    summary_o = symbolic.summarize(original, inputs, int_width, bound)
    summary_c = symbolic.summarize(candidate, inputs, int_width, bound)

    constraints = list(well_formed)
    constraints += symbolic.lower_preconditions(original, inputs, int_width)
    constraints += symbolic.lower_preconditions(candidate, inputs, int_width)
    constraints += summary_o.assumptions + summary_c.assumptions

    # Bound built output lists to length `bound` too (inputs producing longer
    # outputs are out of scope), so the element-wise comparison below is complete.
    cap = z3.BitVecVal(bound, int_width)
    for summary in (summary_o, summary_c):
        if isinstance(summary.output, symbolic.SymList):
            constraints.append(z3.ULE(summary.output.length, cap))

    # Functions differ if their runtime-error behavior differs, or if both
    # complete normally but produce different outputs.
    both_ok = z3.And(z3.Not(summary_o.error), z3.Not(summary_c.error))
    constraints.append(
        z3.Or(
            summary_o.error != summary_c.error,
            z3.And(both_ok, _differ(summary_o.output, summary_c.output, int_width, bound)),
        )
    )
    return inputs, constraints, summary_o, summary_c


def _minimize(constraints, inputs, int_width) -> z3.ModelRef | None:
    """Shrink an (already-SAT) counterexample with a few cheap solver calls.

    Greedy and order-dependent, but fast and robust: first minimize each list's
    length, then pull each scalar int toward zero. Avoids `z3.Optimize`, which is
    slow over bitvectors. Locks in each gain so later steps can't undo it.
    """
    solver = z3.Solver()
    solver.add(*constraints)
    if solver.check() != z3.sat:
        return None  # pragma: no cover — caller already established SAT
    model = solver.model()

    for value in inputs:  # shortest lists first
        if isinstance(value, symbolic.SymList):
            while model.eval(value.length, model_completion=True).as_long() > 0:
                cur = model.eval(value.length, model_completion=True)
                solver.push()
                solver.add(z3.ULT(value.length, cur))
                if solver.check() == z3.sat:
                    model = solver.model()
                    solver.pop()
                else:
                    solver.pop()
                    break
            solver.add(z3.ULE(value.length, model.eval(value.length, model_completion=True)))

    zero = z3.BitVecVal(0, int_width)
    for value in inputs:  # then pull scalar ints to zero where possible
        if z3.is_bv(value):
            solver.push()
            solver.add(value == zero)
            if solver.check() == z3.sat:
                model = solver.model()
                solver.pop()
                solver.add(value == zero)
            else:
                solver.pop()

    return model


def _scope_note(original, candidate, summary_o, summary_c, int_width, bound) -> str:
    bounded_bits = []
    list_io = any(p.type_name == "list[int]" for p in original.params) or original.return_type == "list[int]"
    if list_io:
        bounded_bits.append(f"lists up to length {bound}")
    if summary_o.unrolled or summary_c.unrolled:
        bounded_bits.append(f"loops up to {bound} iterations")
    if bounded_bits:
        return "holds within bound: " + ", ".join(bounded_bits)
    if original.preconditions or candidate.preconditions:
        return f"complete: agree on all {int_width}-bit inputs satisfying the precondition"
    return f"complete: agree on all {int_width}-bit inputs (no loops to bound)"


def _differ(a, b, int_width: int, bound: int) -> z3.ExprRef:
    """Assertion that the two outputs disagree, coercing to a common sort."""
    if isinstance(a, symbolic.SymList) and isinstance(b, symbolic.SymList):
        # Differ if lengths differ, or some in-range element differs.
        element_differs = z3.Or(
            [
                z3.And(
                    z3.ULT(z3.BitVecVal(k, int_width), a.length),
                    z3.Select(a.arr, z3.BitVecVal(k, int_width))
                    != z3.Select(b.arr, z3.BitVecVal(k, int_width)),
                )
                for k in range(bound)
            ]
        )
        return z3.Or(a.length != b.length, element_differs)
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
        original_output=_decode_output(model, summary_original, int_width, bound),
        candidate_output=_decode_output(model, summary_candidate, int_width, bound),
    )


def _decode_output(model: z3.ModelRef, summary: "symbolic.Summary", int_width: int, bound: int) -> object:
    """A function's observable result in the model: a value, a list, or a raised error."""
    if z3.is_true(model.eval(summary.error, model_completion=True)):
        return "<raises>"
    out = summary.output
    if isinstance(out, symbolic.SymList):
        length = int(_to_py(model.eval(out.length, model_completion=True)))
        length = max(0, min(length, bound))
        return [
            _to_py(model.eval(z3.Select(out.arr, z3.BitVecVal(k, int_width)), model_completion=True))
            for k in range(length)
        ]
    return _to_py(model.eval(out, model_completion=True))


def _to_py(value: z3.ExprRef) -> object:
    if z3.is_bool(value):
        return z3.is_true(value)
    if z3.is_bv_value(value):
        return value.as_signed_long()
    return value  # pragma: no cover — unexpected sort, surface it as-is
