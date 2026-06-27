"""Tests for `return` inside loops (M4) — early-exit search patterns."""

from __future__ import annotations

from congruent import check
from congruent.equiv import Status
from congruent.ir import parse_function


def _check(src_a: str, src_b: str, **kw: object) -> object:
    return check(parse_function(src_a, "f"), parse_function(src_b, "g"), **kw)


def test_contains_early_return_equals_flag() -> None:
    early = (
        "def f(xs: list[int], t: int) -> bool:\n"
        "    for x in xs:\n        if x == t:\n            return True\n    return False"
    )
    flag = (
        "def g(xs: list[int], t: int) -> bool:\n    found = False\n"
        "    for x in xs:\n        if x == t:\n            found = True\n    return found"
    )
    verdict = _check(early, flag)
    assert verdict.status is Status.EQUIVALENT
    assert verdict.stage == "symbolic"


def test_first_or_default_loop_equals_indexing() -> None:
    loop = "def f(xs: list[int]) -> int:\n    for x in xs:\n        return x\n    return 0"
    index = "def g(xs: list[int]) -> int:\n    if len(xs) > 0:\n        return xs[0]\n    return 0"
    assert _check(loop, index).status is Status.EQUIVALENT


def test_find_first_index_off_by_one_is_a_counterexample() -> None:
    good = (
        "def f(xs: list[int], t: int) -> int:\n    i = 0\n"
        "    for x in xs:\n        if x == t:\n            return i\n        i = i + 1\n    return -1"
    )
    buggy = (
        "def g(xs: list[int], t: int) -> int:\n    i = 0\n"
        "    for x in xs:\n        if x == t:\n            return i + 1\n        i = i + 1\n    return -1"
    )
    assert _check(good, buggy).status is Status.COUNTEREXAMPLE


def test_break_equivalent_to_early_return_search() -> None:
    # "contains": a flag-and-break loop vs. an early-return loop.
    brk = (
        "def f(xs: list[int], t: int) -> bool:\n    found = False\n"
        "    for x in xs:\n        if x == t:\n            found = True\n            break\n    return found"
    )
    early = (
        "def g(xs: list[int], t: int) -> bool:\n"
        "    for x in xs:\n        if x == t:\n            return True\n    return False"
    )
    assert _check(brk, early).status is Status.EQUIVALENT


def test_continue_equivalent_to_guarded_body() -> None:
    # Counting positives: `continue` on non-positive vs. an `if` guard.
    cont = (
        "def f(xs: list[int]) -> int:\n    c = 0\n"
        "    for x in xs:\n        if x <= 0:\n            continue\n        c = c + 1\n    return c"
    )
    guard = (
        "def g(xs: list[int]) -> int:\n    c = 0\n"
        "    for x in xs:\n        if x > 0:\n            c = c + 1\n    return c"
    )
    assert _check(cont, guard).status is Status.EQUIVALENT


def test_break_off_by_one_is_a_counterexample() -> None:
    # Breaks one element too late: includes the first non-positive in the sum.
    good = (
        "def f(xs: list[int]) -> int:\n    s = 0\n"
        "    for x in xs:\n        if x <= 0:\n            break\n        s = s + x\n    return s"
    )
    buggy = (
        "def g(xs: list[int]) -> int:\n    s = 0\n"
        "    for x in xs:\n        s = s + x\n        if x <= 0:\n            break\n    return s"
    )
    assert _check(good, buggy).status is Status.COUNTEREXAMPLE


def test_early_return_search_bug_caught() -> None:
    # "all positive": early-return False on the first non-positive.
    good = (
        "def f(xs: list[int]) -> bool:\n"
        "    for x in xs:\n        if x <= 0:\n            return False\n    return True"
    )
    buggy = (  # uses < 0, so a 0 slips through as "positive"
        "def g(xs: list[int]) -> bool:\n"
        "    for x in xs:\n        if x < 0:\n            return False\n    return True"
    )
    assert _check(good, buggy).status is Status.COUNTEREXAMPLE
