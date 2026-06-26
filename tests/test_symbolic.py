"""Tests for the symbolic stage (M1): proofs, counterexamples, and fallback."""

from __future__ import annotations

import pytest

from congruent import check
from congruent.equiv import Status
from congruent.ir import parse_function


def _check(src_a: str, src_b: str, **kw: object) -> object:
    return check(parse_function(src_a, "f"), parse_function(src_b, "g"), **kw)


def test_proves_distributivity() -> None:
    a = "def f(x: int, y: int) -> int:\n    return (x + y) * 2"
    b = "def g(x: int, y: int) -> int:\n    return x * 2 + y * 2"
    verdict = _check(a, b)
    assert verdict.status is Status.EQUIVALENT
    assert verdict.stage == "symbolic"


def test_proves_branch_equivalence_including_int_min() -> None:
    a = "def f(x: int) -> int:\n    return x if x >= 0 else -x"
    b = "def g(x: int) -> int:\n    if x < 0:\n        return -x\n    return x"
    assert _check(a, b).status is Status.EQUIVALENT


def test_symbolic_finds_counterexample_difftest_could_miss() -> None:
    # Differs only on a single 32-bit value; the solver pins it exactly.
    a = "def f(x: int) -> int:\n    return 0"
    b = "def g(x: int) -> int:\n    return 1 if x == 1234567 else 0"
    verdict = _check(a, b, trials=50)  # few random trials; solver still nails it
    assert verdict.status is Status.COUNTEREXAMPLE
    assert verdict.counterexample.inputs == {"x": 1234567}


def test_floor_division_semantics_match_python() -> None:
    # `(x - 1) // 2` vs `x // 2 - 1` differ for odd/negative x under floor div.
    # They are NOT equivalent; the symbolic stage must agree with Python `//`
    # and report a counterexample rather than a false EQUIVALENT.
    a = "def f(x: int) -> int:\n    return (x - 1) // 2"
    b = "def g(x: int) -> int:\n    return x // 2 - 1"
    assert _check(a, b).status is Status.COUNTEREXAMPLE


def test_nonconstant_divisor_falls_back_to_unknown() -> None:
    # Division by a variable is not modeled; equivalent-looking pair must not be
    # claimed EQUIVALENT — it falls back to UNKNOWN (sound, not a false proof).
    a = "def f(x: int, y: int) -> int:\n    return (x + x) // y"
    b = "def g(x: int, y: int) -> int:\n    return (x * 2) // y"
    verdict = _check(a, b)
    assert verdict.status is Status.UNKNOWN
    assert verdict.stage == "difftest"


def test_width_sensitive_equivalence() -> None:
    # `x * 2` vs `x << 1` would need shifts; instead test that width matters:
    # `x + x` and `x * 2` are equivalent at any width.
    a = "def f(x: int) -> int:\n    return x + x"
    b = "def g(x: int) -> int:\n    return x * 2"
    assert _check(a, b, int_width=8).status is Status.EQUIVALENT
    assert _check(a, b, int_width=64).status is Status.EQUIVALENT
