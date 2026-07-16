"""Solver backends.

Z3 is the primary engine — it builds the bitvector encoding and produces models
for counterexamples (see `solver.py`). This module adds an *independent*
second opinion: CVC5 re-decides the exact same query (handed over as SMT-LIB2,
so no parallel encoding to keep in sync) purely to cross-check the sat/unsat
verdict. If the two solvers ever disagree, that's a red flag worth surfacing
rather than trusting either answer.

CVC5 is optional; `cvc5_decide` returns `None` when it isn't installed.
"""

from __future__ import annotations

import z3


def cvc5_decide(constraints: list[z3.BoolRef]) -> str | None:
    """Decide a Z3 constraint set with CVC5; return "sat"/"unsat"/"unknown".

    Returns `None` if CVC5 is not installed. The query is round-tripped through
    SMT-LIB2 so CVC5 sees exactly what Z3 saw.
    """
    try:
        import cvc5
    except ImportError:
        return None

    scratch = z3.Solver()
    scratch.add(*constraints)
    # Z3 appends (check-sat); drop it so we drive CVC5's check ourselves, and
    # set a logic up front to silence CVC5's "no set-logic" warning.
    smt2 = "(set-logic ALL)\n" + scratch.to_smt2().replace("(check-sat)", "")

    tm = cvc5.TermManager()
    solver = cvc5.Solver(tm)
    solver.setOption("arrays-exp", "true")  # allow constant arrays (K / store-all)
    parser = cvc5.InputParser(solver)
    parser.setStringInput(cvc5.InputLanguage.SMT_LIB_2_6, smt2, "congruent")
    symbols = parser.getSymbolManager()
    while True:
        command = parser.nextCommand()
        if command.isNull():
            break
        command.invoke(solver, symbols)

    result = solver.checkSat()
    if result.isSat():
        return "sat"
    if result.isUnsat():
        return "unsat"
    return "unknown"
