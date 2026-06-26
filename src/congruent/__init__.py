"""Congruent — bounded behavioral equivalence checking for AI-rewritten code.

Public surface:
    check            — run the equivalence pipeline, return a Verdict.
    Verdict, Status, Counterexample — the result data model.

See README.md for scope and ROADMAP.md for milestones.
"""

from __future__ import annotations

from congruent.equiv import Counterexample, Status, Verdict, check

__version__ = "0.0.1"

__all__ = ["check", "Verdict", "Status", "Counterexample", "__version__"]
