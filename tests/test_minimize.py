"""Tests for counterexample minimization (M5)."""

from __future__ import annotations

from congruent import check
from congruent.equiv import Status
from congruent.ir import parse_function
from congruent.solver import prove_equivalence


def _fns(src_a: str, src_b: str):
    return parse_function(src_a, "f"), parse_function(src_b, "g")


def test_list_counterexample_shrinks_to_shortest() -> None:
    # f = len(xs), g = 2*len(xs): they differ for any non-empty list, so the
    # smallest counterexample is a length-1 list. Go through the symbolic stage
    # directly so minimization (not difftest's boundary list) is what we measure.
    a = "def f(xs: list[int]) -> int:\n    c = 0\n    for x in xs:\n        c = c + 1\n    return c"
    b = "def g(xs: list[int]) -> int:\n    c = 0\n    for x in xs:\n        c = c + 2\n    return c"
    fo, fc = _fns(a, b)
    verdict = prove_equivalence(fo, fc, bound=8, int_width=32, assumptions=[])
    assert verdict.status is Status.COUNTEREXAMPLE
    assert len(verdict.counterexample.inputs["xs"]) == 1
    assert "counterexample minimized" in verdict.assumptions


def test_no_minimize_leaves_counterexample_unshrunk() -> None:
    a = "def f(xs: list[int]) -> int:\n    c = 0\n    for x in xs:\n        c = c + 1\n    return c"
    b = "def g(xs: list[int]) -> int:\n    c = 0\n    for x in xs:\n        c = c + 2\n    return c"
    fo, fc = _fns(a, b)
    verdict = prove_equivalence(fo, fc, bound=8, int_width=32, assumptions=[], minimize=False)
    assert verdict.status is Status.COUNTEREXAMPLE
    assert "counterexample minimized" not in verdict.assumptions


def test_symbolic_counterexample_carries_minimized_note() -> None:
    # x == 1234567 is not a boundary value, so difftest misses it and the
    # symbolic stage produces (and minimizes) the counterexample.
    a = "def f(x: int) -> int:\n    return 0"
    b = "def g(x: int) -> int:\n    return 1 if x == 1234567 else 0"
    verdict = check(*_fns(a, b))
    assert verdict.status is Status.COUNTEREXAMPLE
    assert verdict.counterexample.inputs == {"x": 1234567}
    assert "counterexample minimized" in verdict.assumptions
