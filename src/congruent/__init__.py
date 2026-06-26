"""Congruent — bounded behavioral equivalence checking for AI-rewritten code.

Public surface:
    check            — run the equivalence pipeline, return a Verdict.
    Verdict, Status, Counterexample — the result data model.

See README.md for scope and ROADMAP.md for milestones.
"""

from __future__ import annotations

from congruent.equiv import Counterexample, Status, Verdict, check

__version__ = "0.0.1"


def assume(condition: bool) -> None:
    """Declare an input precondition for the equivalence check.

    A leading ``assume(<expr>)`` in a function tells Congruent to only consider
    inputs satisfying ``<expr>``. Congruent reads these statically; at runtime
    this is a no-op, so source files remain ordinary, runnable Python.
    """
    return None


__all__ = ["check", "Verdict", "Status", "Counterexample", "assume", "__version__"]
