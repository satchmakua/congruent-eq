"""Tests for bounded str support (M7)."""

from __future__ import annotations

from congruent import check
from congruent.equiv import Status
from congruent.ir import parse_function


def _check(src_a: str, src_b: str, **kw: object) -> object:
    return check(parse_function(src_a, "f"), parse_function(src_b, "g"), **kw)


def test_concatenation_is_associative() -> None:
    a = 'def f(s: str, t: str) -> str:\n    return (s + t) + "!"'
    b = 'def g(s: str, t: str) -> str:\n    return s + (t + "!")'
    verdict = _check(a, b)
    assert verdict.status is Status.EQUIVALENT
    assert verdict.stage == "symbolic"


def test_concatenation_is_not_commutative() -> None:
    a = "def f(s: str, t: str) -> str:\n    return s + t"
    b = "def g(s: str, t: str) -> str:\n    return t + s"
    assert _check(a, b).status is Status.COUNTEREXAMPLE


def test_char_count_equivalent() -> None:
    a = 'def f(s: str) -> int:\n    c = 0\n    for ch in s:\n        if ch == "a":\n            c = c + 1\n    return c'
    b = 'def g(s: str) -> int:\n    c = 0\n    for ch in s:\n        if "a" == ch:\n            c = c + 1\n    return c'
    assert _check(a, b).status is Status.EQUIVALENT


def test_rebuild_identity() -> None:
    a = "def f(s: str) -> str:\n    return s"
    b = 'def g(s: str) -> str:\n    r = ""\n    for ch in s:\n        r = r + ch\n    return r'
    assert _check(a, b).status is Status.EQUIVALENT


def test_first_char_via_index_or_loop() -> None:
    a = 'def f(s: str) -> str:\n    if len(s) > 0:\n        return s[0]\n    return ""'
    b = 'def g(s: str) -> str:\n    r = ""\n    for ch in s:\n        return ch\n    return r'
    assert _check(a, b).status is Status.EQUIVALENT


def test_equality_is_not_just_length() -> None:
    a = 'def f(s: str) -> bool:\n    return s == "ab"'
    b = "def g(s: str) -> bool:\n    return len(s) == 2"
    verdict = _check(a, b)
    assert verdict.status is Status.COUNTEREXAMPLE
    assert isinstance(verdict.counterexample.inputs["s"], str)
