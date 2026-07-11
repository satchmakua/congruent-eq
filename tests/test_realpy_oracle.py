"""Soundness guard against interpreter-vs-real-Python divergence.

The concrete interpreter is the ground truth every other check trusts, so a bug it
*shares* with the symbolic stage is otherwise invisible. `benchmarks/realpy_fuzz.py`
independently validates the interpreter against real Python; this runs a fast,
fixed-seed batch so any such regression fails CI. Run the full oracle by hand for
more trials.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "benchmarks"))

import realpy_fuzz  # noqa: E402


def test_interpreter_matches_real_python() -> None:
    messages: list[str] = []
    mismatches = realpy_fuzz.run(trials=400, seed=0, report=messages.append)
    assert mismatches == 0, "interpreter diverged from real Python:\n" + "\n".join(messages[:5])
