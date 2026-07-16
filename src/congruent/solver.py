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

from congruent import backends, symbolic
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
    cross_check: bool = False,
    timeout_ms: int | None = None,
) -> Verdict:
    """Run the symbolic equivalence query for two (signature-matched) functions.

    `UNSAT → EQUIVALENT`, `SAT → COUNTEREXAMPLE` (minimized when `minimize`),
    else `UNKNOWN`. With `cross_check`, CVC5 independently re-decides the query;
    a disagreement downgrades the verdict to `UNKNOWN`. `timeout_ms` caps each Z3
    `check()`; on timeout Z3 returns `unknown`, so a hard-but-modeled query (e.g.
    a high-degree symbolic-coefficient polynomial, where bitvector multiplication
    blows up) degrades to an honest `UNKNOWN` rather than hanging forever.

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
    if timeout_ms is not None:
        solver.set("timeout", timeout_ms)
    solver.add(*constraints)

    start = time.perf_counter()
    result = solver.check()

    extra = list(assumptions)
    if cross_check:
        z3_status = "unsat" if result == z3.unsat else "sat" if result == z3.sat else "unknown"
        other = backends.cvc5_decide(constraints)
        if other is None:
            extra.append("cross-check requested but cvc5 is not installed")
        elif other != z3_status:
            elapsed = time.perf_counter() - start
            return Verdict(
                status=Status.UNKNOWN, bound=bound, solver_time=elapsed, stage="symbolic",
                assumptions=assumptions
                + [f"solver backends disagree (z3={z3_status}, cvc5={other}) — please report"],
            )
        else:
            extra.append("cross-checked with cvc5 (agrees)")

    if result == z3.unsat:
        elapsed = time.perf_counter() - start
        note, complete = _scope_note(original, summary_o, summary_c, int_width, bound)
        return Verdict(
            status=Status.EQUIVALENT,
            bound=bound,
            complete=complete,
            solver_time=elapsed,
            stage="symbolic",
            assumptions=extra + [note],
        )

    if result == z3.unknown:
        elapsed = time.perf_counter() - start
        return Verdict(
            status=Status.UNKNOWN,
            bound=bound,
            solver_time=elapsed,
            stage="symbolic",
            assumptions=extra + [f"solver returned unknown: {solver.reason_unknown()}"],
        )

    # SAT — a counterexample exists. Optionally shrink it to the smallest input.
    model = solver.model()
    notes = list(extra)
    if minimize:
        minimal = _minimize(constraints, inputs, int_width, timeout_ms)
        if minimal is not None:
            model = minimal
            notes.append("counterexample minimized")
    elapsed = time.perf_counter() - start

    cx = _decode_model(model, inputs, original.params, summary_o, summary_c, int_width)
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
    # Only the ORIGINAL's precondition constrains the domain: a precondition the
    # candidate adds is itself a behavioral change (domain narrowing) and must
    # surface as a counterexample, not be assumed away. But a candidate precondition's
    # ARGUMENT is still evaluated at runtime — if it raises (e.g. assume(xs[0] > 0) on
    # []), that is a real divergence, so fold it into the candidate's error.
    constraints += symbolic.lower_preconditions(original, inputs, int_width, bound)
    cand_pre_error = symbolic.precondition_error(candidate, inputs, int_width, bound)
    if not z3.is_false(cand_pre_error):
        summary_c.error = z3.Or(summary_c.error, cand_pre_error)
    constraints += summary_o.assumptions + summary_c.assumptions

    # No output-length cap constraint is needed: each SymList carries its own static
    # max length (`cap`), `length <= cap` holds by construction, and `_differ`
    # compares over that cap — so no in-scope input is ever dropped from the query.

    # Each function's observable outcome is one of: raises, returns None (fell off
    # the end), or returns a value. They differ if those outcomes differ — the
    # error behavior differs, exactly one falls off (None vs a value), or both
    # return a value but the values differ.
    both_ok = z3.And(z3.Not(summary_o.error), z3.Not(summary_c.error))
    constraints.append(
        z3.Or(
            summary_o.error != summary_c.error,
            z3.And(both_ok, summary_o.fell_off != summary_c.fell_off),
            z3.And(
                both_ok, z3.Not(summary_o.fell_off), z3.Not(summary_c.fell_off),
                _differ(summary_o.output, summary_c.output, int_width),
            ),
        )
    )
    return inputs, constraints, summary_o, summary_c


def _minimize(constraints, inputs, int_width, timeout_ms=None) -> z3.ModelRef | None:
    """Shrink an (already-SAT) counterexample with a few cheap solver calls.

    Greedy and order-dependent, but fast and robust: first minimize each list's
    length, then pull each scalar int toward zero. Avoids `z3.Optimize`, which is
    slow over bitvectors. Locks in each gain so later steps can't undo it. A
    `timeout_ms` on each call just stops shrinking early (the best model so far is
    still a valid counterexample)."""
    solver = z3.Solver()
    if timeout_ms is not None:
        solver.set("timeout", timeout_ms)
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


def _scope_note(original, summary_o, summary_c, int_width, bound) -> tuple[str, bool]:
    """The scope caveat for an EQUIVALENT verdict, plus whether it is *complete*
    (nothing was bounded away, so `bound` is not a limitation on the result)."""
    bounded_bits = []
    seq_types = {"list[int]", "str"}
    seq_io = any(p.type_name in seq_types for p in original.params) or original.return_type in seq_types
    if seq_io:
        bounded_bits.append(f"lists/strings up to length {bound}")
    if summary_o.unrolled or summary_c.unrolled:
        bounded_bits.append(f"loops up to {bound} iterations")
    if bounded_bits:
        return "holds within bound: " + ", ".join(bounded_bits), False
    if original.preconditions:
        return f"complete: agree on all {int_width}-bit inputs satisfying the precondition", True
    return f"complete: agree on all {int_width}-bit inputs (no loops to bound)", True


def _differ(a, b, int_width: int) -> z3.ExprRef:
    """Assertion that the two outputs disagree, coercing to a common sort."""
    if isinstance(a, symbolic.SymList) and isinstance(b, symbolic.SymList):
        # Differ if lengths differ, or some in-range element differs. Compare over
        # the larger static capacity so a longer computed output is fully covered.
        element_differs = z3.Or(
            [
                z3.And(
                    z3.ULT(z3.BitVecVal(k, int_width), a.length),
                    z3.Select(a.arr, z3.BitVecVal(k, int_width))
                    != z3.Select(b.arr, z3.BitVecVal(k, int_width)),
                )
                for k in range(max(a.cap, b.cap))
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
    summary_original: symbolic.Summary,
    summary_candidate: symbolic.Summary,
    int_width: int,
) -> Counterexample:
    """Turn a satisfying model into a concrete `Counterexample`."""
    concrete: dict[str, object] = {}
    for param, value in zip(params, inputs):
        if isinstance(value, symbolic.SymList):
            concrete[param.name] = _decode_seq(model, value, int_width)
        else:
            concrete[param.name] = _to_py(model.eval(value, model_completion=True))
    return Counterexample(
        inputs=concrete,
        original_output=_decode_output(model, summary_original, int_width),
        candidate_output=_decode_output(model, summary_candidate, int_width),
    )


def _decode_seq(model: z3.ModelRef, sym: symbolic.SymList, int_width: int) -> object:
    """Decode a SymList model value: a `str` (kind char) or a `list[int]`."""
    length = int(_to_py(model.eval(sym.length, model_completion=True)))
    length = max(0, min(length, sym.cap))
    elements = [
        int(_to_py(model.eval(z3.Select(sym.arr, z3.BitVecVal(k, int_width)), model_completion=True)))
        for k in range(length)
    ]
    if sym.kind == "char":
        return "".join(chr(e) if 0 <= e <= 0x10FFFF else "�" for e in elements)
    return elements


def _decode_output(model: z3.ModelRef, summary: symbolic.Summary, int_width: int) -> object:
    """A function's observable result in the model: a value, a sequence, None, or a raised error."""
    if z3.is_true(model.eval(summary.error, model_completion=True)):
        return "<raises>"
    if z3.is_true(model.eval(summary.fell_off, model_completion=True)):
        return None  # fell off the end without returning
    out = summary.output
    if isinstance(out, symbolic.SymList):
        return _decode_seq(model, out, int_width)
    return _to_py(model.eval(out, model_completion=True))


def _to_py(value):  # -> Any: a decoded model value (bool / signed int)
    if z3.is_bool(value):
        return z3.is_true(value)
    if z3.is_bv_value(value):
        return value.as_signed_long()
    return value  # pragma: no cover — unexpected sort, surface it as-is
