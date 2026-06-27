"""Soundness regression guard: a small deterministic fuzz batch must be clean.

The full fuzzer lives in `benchmarks/fuzz.py` (run it with more trials by hand);
here we run a fast, fixed-seed batch so any regression that introduces an unsound
verdict fails CI.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "benchmarks"))

import fuzz  # noqa: E402


def test_no_unsound_verdicts_in_fuzz_batch() -> None:
    messages: list[str] = []
    violations = fuzz.run(trials=200, seed=0, sample=120, report=messages.append)
    assert violations == 0, "unsound verdicts:\n" + "\n".join(messages)
