"""Regression tests for soundness bugs found by the adversarial audit.

Each of these once produced an UNSOUND verdict (a false EQUIVALENT or false
COUNTEREXAMPLE) or a crash. They must stay fixed.
"""

from __future__ import annotations

import pytest

from congruent import check
from congruent.equiv import Status
from congruent.ir import parse_function as P


def _v(a: str, b: str, **kw):
    return check(P(a, "f"), P(b, "g"), **kw)


def test_non_ascii_string_is_not_falsely_equivalent() -> None:
    # str code points were constrained to ASCII, so `s == "é"` was proven
    # EQUIVALENT to a function that never matches. It must be a counterexample.
    a = 'def f(s: str) -> bool:\n    return s == "é"'
    b = "def g(s: str) -> bool:\n    return False"
    verdict = _v(a, b)
    assert verdict.status is Status.COUNTEREXAMPLE
    assert verdict.counterexample.inputs["s"] == "é"


def test_foreach_over_computed_sequence_is_not_falsely_disproven() -> None:
    # `for v in xs + [1]` builds a sequence longer than bound; the symbolic stage
    # used to silently drop the tail and fabricate a counterexample.
    a = "def f(xs: list[int]) -> int:\n    t = 0\n    for v in xs + [1]:\n        t = t + v\n    return t"
    b = "def g(xs: list[int]) -> int:\n    t = 1\n    for v in xs:\n        t = t + v\n    return t"
    assert _v(a, b, bound=2).status is not Status.COUNTEREXAMPLE


def test_loop_variable_after_loop_is_not_a_false_counterexample() -> None:
    # env.pop of the loop var fabricated a NameError -> false COUNTEREXAMPLE.
    a = "def f(n: int) -> int:\n    assume(n >= 1)\n    for i in range(n):\n        pass\n    return i"
    b = "def g(n: int) -> int:\n    assume(n >= 1)\n    return n - 1"
    assert _v(a, b).status is not Status.COUNTEREXAMPLE


def test_candidate_precondition_cannot_hide_a_divergence() -> None:
    # A candidate-only assume() narrowed the domain to exclude the diverging input.
    a = "def f(x: int) -> int:\n    return 5"
    b = "def g(x: int) -> int:\n    assume(x != 0)\n    return 5 if x != 0 else 999"
    verdict = _v(a, b)
    assert verdict.status is Status.COUNTEREXAMPLE
    assert verdict.counterexample.inputs["x"] == 0


def test_both_raise_is_consistent_across_stages() -> None:
    # Two functions that always raise (different exception types) must get the
    # same verdict whether difftest or the symbolic stage decides.
    a = "def f(xs: list[int]) -> int:\n    return xs[100]"
    b = "def g(xs: list[int]) -> int:\n    return xs[0] // 0"
    assert _v(a, b).status is Status.EQUIVALENT  # both always error -> equivalent


def test_error_vs_value_is_still_a_counterexample() -> None:
    # Collapsing error *types* must not collapse error-vs-value.
    a = "def f(x: int) -> int:\n    return 100 // x"  # raises at x == 0
    b = "def g(x: int) -> int:\n    return 100 // x if x != 0 else 0"
    assert _v(a, b).status is Status.COUNTEREXAMPLE


def test_c_octal_literal_does_not_crash() -> None:
    cfront = pytest.importorskip("congruent.cfront")
    fn = cfront.parse_c_function("int f(int x) { return x + 010; }", "f")
    assert fn.body[0].value.right.value == 8  # 010 (octal) == 8


def test_c_void_parameter_list() -> None:
    cfront = pytest.importorskip("congruent.cfront")
    assert cfront.parse_c_function("int f(void) { return 1; }", "f").params == []


def test_c_escaping_loop_counter_is_rejected() -> None:
    cfront = pytest.importorskip("congruent.cfront")
    from congruent.ir import UnsupportedConstruct

    with pytest.raises(UnsupportedConstruct):
        cfront.parse_c_function("int f(int i) { for (i = 0; i < 3; i = i + 1) {} return i; }", "f")


# --- second round (re-audit of the fixes) ----------------------------------

def test_loop_var_shadowing_param_is_not_falsely_equivalent() -> None:
    # The loop var must fall out of scope even when nested in an if and shadowing
    # a param, so a later `return i` cannot revert to the stale param value.
    a = "def f(i: int, k: int) -> int:\n    if k == 1234567:\n        for i in range(0, 2):\n            pass\n    return i"
    b = "def g(i: int, k: int) -> int:\n    return i"
    assert _v(a, b, bound=4).status is not Status.EQUIVALENT


def test_precondition_that_raises_excludes_the_input() -> None:
    # `assume(100 // x < 0)` cannot be evaluated at x == 0, so x == 0 is out of
    # domain (like difftest excludes it) and the pair is equivalent on x < 0.
    a = "def f(x: int) -> int:\n    assume(100 // x < 0)\n    return 5"
    b = "def g(x: int) -> int:\n    assume(100 // x < 0)\n    return 5 if x != 0 else 100 // x"
    assert _v(a, b).status is Status.EQUIVALENT


def test_str_declines_at_small_int_width() -> None:
    # Code points would wrap for int_width < 22, so the symbolic stage must not
    # certify a non-ASCII-distinguishing pair as equivalent.
    a = 'def f(s: str) -> bool:\n    return s == "鱀"'  # U+9C40 = 40000
    b = "def g(s: str) -> bool:\n    return False"
    assert _v(a, b, int_width=16).status is not Status.EQUIVALENT


def test_sequence_equality_covers_computed_length() -> None:
    a = "def f(xs: list[int]) -> bool:\n    return (xs + [0]) == (xs + [1])"
    b = "def g(xs: list[int]) -> bool:\n    return False"
    assert _v(a, b, bound=3).status is not Status.COUNTEREXAMPLE


def test_output_longer_than_bound_is_not_falsely_equivalent() -> None:
    # `xs + xs` output is 2*len(xs); an input of length 6 (in scope) must not be
    # dropped from the divergence query by an output-length cap.
    a = "def f(xs: list[int]) -> list[int]:\n    return xs + xs"
    b = "def g(xs: list[int]) -> list[int]:\n    return xs + [0] if len(xs) >= 6 and xs[0] == xs[5] else xs + xs"
    assert _v(a, b).status is Status.COUNTEREXAMPLE


def test_c_counter_read_only_before_loop_is_accepted() -> None:
    cfront = pytest.importorskip("congruent.cfront")
    # `t = p` reads p strictly before the loop — must not be rejected.
    fn = cfront.parse_c_function(
        "int f(int p) { int t = p; for (p = 0; p < 3; p = p + 1) { t = t + p; } return t; }", "f"
    )
    assert fn.name == "f"


# --- third round (re-audit of the round-2 fixes) ---------------------------

def test_concat_chain_cap_does_not_hide_an_in_scope_divergence() -> None:
    # `xs + xs + xs` (length 3*bound) once injected `length <= 2*bound`, excluding
    # length-bound inputs from the query -> a false EQUIVALENT (the cardinal sin).
    # The cap must be the sequence's own static max length, dropping no in-scope input.
    a = "def f(xs: list[int]) -> int:\n    ys = xs + xs + xs\n    return len(xs)"
    b = (
        "def g(xs: list[int]) -> int:\n"
        "    if len(xs) == 2:\n"
        "        if xs[0] == 42:\n"
        "            if xs[1] == 42:\n"
        "                return 99\n"
        "    return len(xs)"
    )
    verdict = _v(a, b, bound=2, int_width=8)
    assert verdict.status is Status.COUNTEREXAMPLE
    assert verdict.counterexample.inputs["xs"] == [42, 42]


def test_deep_concat_chain_equivalence_is_still_proven() -> None:
    # The exact-cap comparison must not over-report: a genuinely equivalent chain
    # (3*len) stays EQUIVALENT, not a fabricated counterexample.
    a = "def f(xs: list[int]) -> int:\n    ys = xs + xs + xs\n    return len(ys)"
    b = "def g(xs: list[int]) -> int:\n    return 3 * len(xs)"
    assert _v(a, b, bound=2, int_width=8).status is Status.EQUIVALENT


def test_pathological_sequence_growth_declines_to_unknown() -> None:
    # Doubling a list inside a loop makes the static cap explode; the symbolic stage
    # must fail closed (UNKNOWN), never silently exclude inputs or hang.
    a = "def f(xs: list[int]) -> int:\n    ys = xs\n    for i in range(2):\n        ys = ys + ys\n    return len(ys)"
    b = "def g(xs: list[int]) -> int:\n    return len(xs) * 4"
    assert _v(a, b, bound=8, int_width=8).status is Status.UNKNOWN


def test_str_never_equals_list_of_matching_code_points() -> None:
    # `_seq_eq` compared a str and a list[int] by contents, so `s == xs` was found
    # satisfiable -> a spurious counterexample. In Python a str never equals a list.
    a = "def f(s: str, xs: list[int]) -> bool:\n    return s == xs"
    b = "def g(s: str, xs: list[int]) -> bool:\n    return False"
    assert _v(a, b, bound=2, int_width=32).status is Status.EQUIVALENT
