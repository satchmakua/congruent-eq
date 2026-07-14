"""Independent fixed-width oracle: numpy's C two's-complement arithmetic vs. ours.

Every other soundness check validates the interpreter against real Python at a
width wide enough that nothing overflows — so the *wrapping* itself was only ever
checked by construction and hand-written cases. `benchmarks/numpy_oracle.py`
closes that with an independent reference (numpy fixed-width scalars). This runs a
fast, fixed-seed slice so a regression in the wrapping model fails CI; run the
full oracle by hand for more trials/widths.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("numpy")  # the oracle is an optional dev dependency (`pip install .[oracle]`)
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "benchmarks"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy_oracle  # noqa: E402
from congruent.difftest import _apply_binop, _int_min_max, _wrap  # noqa: E402

_DTYPES = {8: np.int8, 16: np.int16, 32: np.int32, 64: np.int64}


def test_exhaustive_primitive_parity_at_width_8() -> None:
    # The strongest single check: for EVERY pair of 8-bit integers, Congruent's
    # (mask + sign-adjust) arithmetic must equal numpy's C two's-complement — for
    # +, -, *, // and % (nonzero divisor) and unary negation. This nails the exact
    # overflow edges (INT_MIN * -1, INT_MIN // -1, INT_MAX + 1, ...) by enumeration.
    width, dt = 8, _DTYPES[8]
    imin, imax = _int_min_max(width)
    vals = range(imin, imax + 1)

    def cong(op: str, a: int, b: int) -> int:
        return _wrap(_apply_binop(op, a, b), width)

    def npy(op: str, a: int, b: int) -> int:
        x, y = dt(a), dt(b)
        return int({"+": x + y, "-": x - y, "*": x * y, "//": x // y, "%": x % y}[op])

    for a in vals:
        assert _wrap(-a, width) == int(-dt(a)), f"unary - diverges at {a}"
        for b in vals:
            for op in ("+", "-", "*"):
                assert cong(op, a, b) == npy(op, a, b), f"{a} {op} {b}"
            if b != 0:
                for op in ("//", "%"):
                    assert cong(op, a, b) == npy(op, a, b), f"{a} {op} {b}"


def test_int_min_div_neg_one_wraps_the_same_both_ways() -> None:
    # INT_MIN // -1 overflows (the quotient is INT_MAX+1); both engines must wrap
    # it to INT_MIN rather than one raising or disagreeing. Not special-cased in
    # the oracle — this asserts the wrapping falls out naturally.
    for width in (8, 16, 32):
        imin, _ = _int_min_max(width)
        dt = _DTYPES[width]
        assert _wrap(_apply_binop("//", imin, -1), width) == imin
        assert int(dt(imin) // dt(-1)) == imin


def test_fuzz_agrees_across_widths() -> None:
    messages: list[str] = []
    total = 0
    for width in (8, 16, 32, 64):
        total += numpy_oracle.run(trials=300, seed=0, width=width, report=messages.append)
    assert total == 0, "numpy oracle diverged from the interpreter:\n" + "\n".join(messages[:5])
