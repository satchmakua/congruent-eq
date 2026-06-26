"""Tests for functions that build and return list[int] (M6)."""

from __future__ import annotations

from congruent import check
from congruent.equiv import Status
from congruent.ir import parse_function

_MAP = "def {n}(xs: list[int]) -> list[int]:\n r = []\n for x in xs:\n  r = r + [{e}]\n return r"


def _check(src_a: str, src_b: str, **kw: object) -> object:
    return check(parse_function(src_a, "f"), parse_function(src_b, "g"), **kw)


def test_map_rewrite_is_equivalent() -> None:
    verdict = _check(_MAP.format(n="f", e="x * 2"), _MAP.format(n="g", e="x + x"))
    assert verdict.status is Status.EQUIVALENT
    assert verdict.stage == "symbolic"


def test_map_off_by_one_is_a_counterexample() -> None:
    assert _check(_MAP.format(n="f", e="x * 2"), _MAP.format(n="g", e="x * 2 + 1")).status is Status.COUNTEREXAMPLE


def test_filter_rewrite_is_equivalent() -> None:
    a = "def f(xs: list[int]) -> list[int]:\n r = []\n for x in xs:\n  if x > 0:\n   r = r + [x]\n return r"
    b = "def g(xs: list[int]) -> list[int]:\n r = []\n for x in xs:\n  if x >= 1:\n   r = r + [x]\n return r"
    assert _check(a, b).status is Status.EQUIVALENT


def test_identity_rebuild_is_equivalent() -> None:
    a = "def f(xs: list[int]) -> list[int]:\n return xs"
    b = "def g(xs: list[int]) -> list[int]:\n r = []\n for x in xs:\n  r = r + [x]\n return r"
    assert _check(a, b).status is Status.EQUIVALENT


def test_concatenation_is_not_commutative() -> None:
    a = "def f(xs: list[int], ys: list[int]) -> list[int]:\n return xs + ys"
    b = "def g(xs: list[int], ys: list[int]) -> list[int]:\n return ys + xs"
    assert _check(a, b).status is Status.COUNTEREXAMPLE


def test_return_type_mismatch_is_an_error() -> None:
    a = "def f(xs: list[int]) -> int:\n return len(xs)"
    b = "def g(xs: list[int]) -> list[int]:\n return xs"
    assert _check(a, b).status is Status.ERROR
