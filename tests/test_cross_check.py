"""Tests for the CVC5 cross-check backend (M7). Skipped if cvc5 isn't installed."""

from __future__ import annotations

import pytest

pytest.importorskip("cvc5")

import z3  # noqa: E402

from congruent import backends, check  # noqa: E402
from congruent.equiv import Status  # noqa: E402
from congruent.ir import parse_function  # noqa: E402


def _check(src_a: str, src_b: str, **kw: object) -> object:
    return check(parse_function(src_a, "f"), parse_function(src_b, "g"), **kw)


def test_cvc5_decide_matches_z3() -> None:
    x = z3.BitVec("x", 8)
    assert backends.cvc5_decide([x + 1 == 0]) == "sat"
    assert backends.cvc5_decide([x != x]) == "unsat"


def test_cross_check_agrees_on_equivalent() -> None:
    a = "def f(x: int, y: int) -> int:\n    return (x + y) * 2"
    b = "def g(x: int, y: int) -> int:\n    return x * 2 + y * 2"
    verdict = _check(a, b, cross_check=True)
    assert verdict.status is Status.EQUIVALENT
    assert any("cross-checked with cvc5" in note for note in verdict.assumptions)


def test_cross_check_agrees_on_counterexample() -> None:
    a = "def f(x: int) -> int:\n    return 0"
    b = "def g(x: int) -> int:\n    return 1 if x == 42 else 0"
    verdict = _check(a, b, cross_check=True)
    assert verdict.status is Status.COUNTEREXAMPLE
    assert any("cross-checked with cvc5" in note for note in verdict.assumptions)


@pytest.mark.parametrize(
    "src",
    [
        "def {n}(x: int) -> int:\n    return x if x >= 0 else -x",  # abs (EQUIVALENT pair below)
        "def {n}(n: int) -> int:\n    t = 0\n    for i in range(n):\n        t = t + i\n    return t",  # loop
        "def {n}(xs: list[int]) -> int:\n    return len(xs)",  # array
    ],
)
def test_backends_agree_on_self_equivalence(src: str) -> None:
    # A function is trivially equivalent to itself; cvc5 must agree (UNSAT).
    verdict = _check(src.format(n="f"), src.format(n="g"), cross_check=True)
    assert verdict.status is Status.EQUIVALENT
    assert not any("disagree" in note for note in verdict.assumptions)
