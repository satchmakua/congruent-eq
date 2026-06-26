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


def test_indexing_difference_is_caught() -> None:
    a = "def f(xs: list[int]) -> int:\n    return xs[0]"
    b = "def g(xs: list[int]) -> int:\n    return xs[1]"
    assert _check(a, b).status is Status.COUNTEREXAMPLE


def test_identical_indexing_is_proven_equivalent() -> None:
    # Both index the same way: same out-of-bounds behavior AND same value, so the
    # symbolic stage proves equivalence (it models OOB as a matching error).
    src = "def {name}(xs: list[int]) -> int:\n    return xs[0] + xs[0]"
    verdict = _check(src.format(name="f"), src.format(name="g"))
    assert verdict.status is Status.EQUIVALENT
    assert verdict.stage == "symbolic"


def test_guarded_indexing_is_proven_equivalent() -> None:
    a = "def f(xs: list[int]) -> int:\n    if len(xs) > 0:\n        return xs[0]\n    return 0"
    b = (
        "def g(xs: list[int]) -> int:\n    r = 0\n"
        "    if 0 < len(xs):\n        r = xs[0]\n    return r"
    )
    assert _check(a, b).status is Status.EQUIVALENT


def test_out_of_bounds_divergence_is_a_counterexample() -> None:
    # original indexes unconditionally (raises on []); candidate guards it.
    a = "def f(xs: list[int]) -> int:\n    return xs[0]"
    b = "def g(xs: list[int]) -> int:\n    if len(xs) > 0:\n        return xs[0]\n    return 0"
    verdict = _check(a, b)
    assert verdict.status is Status.COUNTEREXAMPLE
    assert verdict.counterexample.inputs["xs"] == []  # diverge on the empty list