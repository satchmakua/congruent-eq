"""Unit tests for the differential stage and the fixed-width integer model."""

from __future__ import annotations

from congruent import check
from congruent.difftest import _wrap
from congruent.equiv import Status
from congruent.ir import parse_function


def _check(src_a: str, src_b: str, **kw: object) -> object:
    return check(parse_function(src_a, "f"), parse_function(src_b, "g"), **kw)


def test_wrap_two_complement() -> None:
    assert _wrap(2**31, 32) == -(2**31)        # INT_MAX + 1 wraps to INT_MIN
    assert _wrap(2**32, 32) == 0
    assert _wrap(-1, 32) == -1
    assert _wrap(2**31 - 1, 32) == 2**31 - 1   # INT_MAX is unchanged


def test_overflow_counterexample_is_found() -> None:
    # The midpoint bug: equal under unbounded ints, divergent at 32-bit width.
    a = "def f(lo: int, hi: int) -> int:\n    return lo + (hi - lo) // 2"
    b = "def g(lo: int, hi: int) -> int:\n    return (lo + hi) // 2"
    verdict = _check(a, b, int_width=32)
    assert verdict.status is Status.COUNTEREXAMPLE
    cx = verdict.counterexample
    assert set(cx.inputs) == {"lo", "hi"}


def test_commutative_pair_not_disproven() -> None:
    a = "def f(x: int, y: int) -> int:\n    return x + y"
    b = "def g(x: int, y: int) -> int:\n    return y + x"
    assert _check(a, b).status is not Status.COUNTEREXAMPLE


def test_mismatched_signatures_error() -> None:
    a = "def f(x: int) -> int:\n    return x"
    b = "def g(x: int, y: int) -> int:\n    return x"
    assert _check(a, b).status is Status.ERROR


def test_diverging_exception_is_a_counterexample() -> None:
    # f never divides; g divides by a value that is zero at x == 0.
    a = "def f(x: int) -> int:\n    return 1"
    b = "def g(x: int) -> int:\n    return 1 + 100 // x"
    verdict = _check(a, b)
    assert verdict.status is Status.COUNTEREXAMPLE
    assert verdict.counterexample.inputs == {"x": 0}


def test_verdict_is_reproducible() -> None:
    a = "def f(x: int) -> int:\n    return x * 2"
    b = "def g(x: int) -> int:\n    return x + x"
    assert _check(a, b, seed=1).status == _check(a, b, seed=2).status
