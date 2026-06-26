"""Tests for list[int] support (M2 arrays)."""

from __future__ import annotations

from congruent import check
from congruent.equiv import Status
from congruent.ir import parse_function


def _check(src_a: str, src_b: str, **kw: object) -> object:
    return check(parse_function(src_a, "f"), parse_function(src_b, "g"), **kw)


def test_len_equals_manual_count() -> None:
    a = "def f(xs: list[int]) -> int:\n    return len(xs)"
    b = "def g(xs: list[int]) -> int:\n    c = 0\n    for x in xs:\n        c = c + 1\n    return c"
    verdict = _check(a, b)
    assert verdict.status is Status.EQUIVALENT
    assert verdict.stage == "symbolic"


def test_sum_reorder_is_equivalent() -> None:
    a = "def f(xs: list[int]) -> int:\n    t = 0\n    for x in xs:\n        t = t + x\n    return t"
    b = "def g(xs: list[int]) -> int:\n    t = 0\n    for x in xs:\n        t = x + t\n    return t"
    assert _check(a, b).status is Status.EQUIVALENT


def test_array_verdict_reports_length_bound() -> None:
    a = "def f(xs: list[int]) -> int:\n    return len(xs)"
    b = "def g(xs: list[int]) -> int:\n    c = 0\n    for x in xs:\n        c = c + 1\n    return c"
    verdict = _check(a, b, bound=5)
    assert any("lists up to length 5" in note for note in verdict.assumptions)


def test_count_off_by_one_is_a_counterexample() -> None:
    a = (
        "def f(xs: list[int]) -> int:\n    c = 0\n"
        "    for x in xs:\n        if x > 0:\n            c = c + 1\n    return c"
    )
    b = (
        "def g(xs: list[int]) -> int:\n    c = 0\n"
        "    for x in xs:\n        if x >= 0:\n            c = c + 1\n    return c"
    )
    verdict = _check(a, b)
    assert verdict.status is Status.COUNTEREXAMPLE
    assert 0 in verdict.counterexample.inputs["xs"]  # the diverging list contains 0


def test_indexing_difference_is_caught_by_difftest() -> None:
    a = "def f(xs: list[int]) -> int:\n    return xs[0]"
    b = "def g(xs: list[int]) -> int:\n    return xs[1]"
    assert _check(a, b).status is Status.COUNTEREXAMPLE


def test_indexing_falls_back_to_unknown_in_proofs() -> None:
    # Identical functions that index: difftest finds nothing, the symbolic stage
    # declines to model xs[i] -> UNKNOWN (never a false EQUIVALENT).
    src = "def {name}(xs: list[int]) -> int:\n    return xs[0] + xs[0]"
    verdict = _check(src.format(name="f"), src.format(name="g"))
    assert verdict.status is Status.UNKNOWN