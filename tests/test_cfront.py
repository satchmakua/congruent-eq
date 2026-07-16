"""Tests for the C front end (M7 stretch). Skipped if pycparser isn't installed."""

from __future__ import annotations

import pytest

pytest.importorskip("pycparser")

from congruent import check  # noqa: E402
from congruent.cfront import parse_c_function  # noqa: E402
from congruent.equiv import Status  # noqa: E402
from congruent.ir import UnsupportedConstruct, parse_function  # noqa: E402


def _check(src_a: str, src_b: str, **kw: object) -> object:
    return check(parse_c_function(src_a, "f"), parse_c_function(src_b, "g"), **kw)


def test_c_midpoint_is_a_counterexample() -> None:
    a = "int f(int lo, int hi) { return lo + (hi - lo) / 2; }"
    b = "int g(int lo, int hi) { return (lo + hi) / 2; }"
    assert _check(a, b).status is Status.COUNTEREXAMPLE


def test_c_distributivity_is_equivalent() -> None:
    a = "int f(int x, int y) { return (x + y) * 2; }"
    b = "int g(int x, int y) { return x * 2 + y * 2; }"
    verdict = _check(a, b)
    assert verdict.status is Status.EQUIVALENT
    assert verdict.stage == "symbolic"


def test_c_abs_branch_equivalent() -> None:
    a = "int f(int x) { return x >= 0 ? x : -x; }"
    b = "int g(int x) { if (x < 0) return -x; return x; }"
    assert _check(a, b).status is Status.EQUIVALENT


def test_c_loop_reorder_equivalent() -> None:
    a = "int f(int n) { int t = 0; for (int i = 0; i < n; i++) { t = t + i; } return t; }"
    b = "int g(int n) { int t = 0; for (int i = 0; i < n; i++) { t = t + (n - 1 - i); } return t; }"
    assert _check(a, b).status is Status.EQUIVALENT


def test_c_break_search_equivalent() -> None:
    a = "int f(int n) { int found = 0; for (int i = 0; i < n; i++) { if (i == 3) found = 1; } return found; }"
    b = "int g(int n) { int found = 0; for (int i = 0; i < n; i++) { if (i == 3) { found = 1; break; } } return found; }"
    assert _check(a, b).status is Status.EQUIVALENT


def test_c_truncating_division_differs_from_python_floor() -> None:
    # C `/` truncates toward zero (-1/2 == 0); Python `//` floors (-1//2 == -1).
    c_fn = parse_c_function("int f(int x) { return x / 2; }", "f")
    py_fn = parse_function("def g(x: int) -> int:\n    return x // 2", "g")
    assert check(c_fn, py_fn).status is Status.COUNTEREXAMPLE


@pytest.mark.parametrize(
    "src",
    [
        "int f(int x) { while (x) { x = x - 1; } return x; }",  # while loop
        "int f(int *p) { return *p; }",  # pointer param
        "int f(int x) { return x & 1; }",  # bitwise operator
        "double f(double x) { return x; }",  # float type
    ],
)
def test_c_unsupported_constructs_raise(src: str) -> None:
    with pytest.raises(UnsupportedConstruct):
        parse_c_function(src, "f")


@pytest.mark.parametrize(
    "src",
    [
        "int f(int x) { break; return x; }",
        "int f(int x) { continue; return x; }",
        "int f(int x) { if (x > 0) { break; } return x; }",
    ],
)
def test_c_loop_control_outside_a_loop_is_rejected(src: str) -> None:
    # The C front end used to accept these silently — the Python front end has
    # always rejected them — handing the two stages an IR they model
    # inconsistently. Both front ends must enforce the same rule.
    with pytest.raises(UnsupportedConstruct, match="outside a loop"):
        parse_c_function(src, "f")
