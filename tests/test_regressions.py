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


def test_negative_index_is_python_not_an_error() -> None:
    # Both stages modeled `xs[-1]` as out-of-range, matching an unrelated error ->
    # a false EQUIVALENT vs real Python (where xs[-1] is the last element).
    a = "def f(xs: list[int]) -> int:\n    return xs[-1]"
    b = "def g(xs: list[int]) -> int:\n    return xs[0] // 0"
    assert _v(a, b, bound=3, int_width=8).status is Status.COUNTEREXAMPLE


def test_negative_index_matches_end_relative_index() -> None:
    # xs[-1] must be provably equivalent to xs[len(xs)-1].
    a = "def f(xs: list[int]) -> int:\n    return xs[-1]"
    b = "def g(xs: list[int]) -> int:\n    return xs[len(xs) - 1]"
    assert _v(a, b, bound=3, int_width=8).status is Status.EQUIVALENT


# --- fourth round (multi-agent adversarial audit) --------------------------

def test_str_plus_list_is_a_type_error_not_a_concatenation() -> None:
    # `s + [1]` mixes str and list -> TypeError in Python; the symbolic stage used
    # to model it as element concat (append 1 vs 2), fabricating a counterexample.
    a = 'def f(s: str) -> str:\n    return s + [1]'
    b = 'def g(s: str) -> str:\n    return s + [2]'
    assert _v(a, b, bound=2, int_width=32).status is Status.EQUIVALENT  # both always raise


def test_list_plus_str_is_a_type_error_not_a_concatenation() -> None:
    a = 'def f(xs: list[int]) -> list[int]:\n    return xs + "a"'
    b = 'def g(xs: list[int]) -> list[int]:\n    return xs + "b"'
    assert _v(a, b, bound=2, int_width=32).status is Status.EQUIVALENT  # both always raise


def test_genuine_str_concat_still_detects_divergence() -> None:
    # Guard the fix above didn't over-broaden: real str concat must still work.
    a = "def f(s: str, t: str) -> str:\n    return s + t"
    b = "def g(s: str, t: str) -> str:\n    return t + s"
    assert _v(a, b, bound=2, int_width=32).status is Status.COUNTEREXAMPLE


def test_bool_return_annotation_does_not_collapse_an_int_return() -> None:
    # Python does not enforce `-> bool`; `return x + y` returns the int. Collapsing
    # it to a truthiness bool made 88 and 89 both True -> a false EQUIVALENT.
    a = "def f(x: int, y: int) -> bool:\n    return x + y"
    b = "def g(x: int, y: int) -> bool:\n    return x + y + (1 if x == 37 and y == 51 else 0)"
    verdict = _v(a, b, bound=2, int_width=8)
    assert verdict.status is Status.COUNTEREXAMPLE
    assert verdict.counterexample.inputs == {"x": 37, "y": 51}


def test_genuine_bool_functions_still_prove_equivalent() -> None:
    a = "def f(x: int) -> bool:\n    return x > 0"
    b = "def g(x: int) -> bool:\n    return x >= 1"
    assert _v(a, b, bound=2, int_width=8).status is Status.EQUIVALENT


def test_nested_loop_variable_shadowing_param_does_not_revert() -> None:
    # An inner loop var shadowing a param is excluded from the outer loop's merged
    # names, so after the loops `return p` reverted to the stale param -> false
    # counterexample. It must not: the sound outcome is UNKNOWN (declines).
    a = "def f(p: int) -> int:\n    for i in range(2):\n        for p in range(2):\n            pass\n    return p"
    b = "def g(p: int) -> int:\n    return 1"
    assert _v(a, b, bound=2, int_width=8).status is not Status.COUNTEREXAMPLE


def test_foreach_over_computed_sequence_reports_real_divergence() -> None:
    # Iterating `xs + xs` (length 2*len) is faithful to Python: xs=[0,0] iterates 4
    # elements and f/g genuinely diverge there. This must stay a COUNTEREXAMPLE — a
    # guard against re-adding a `seq.length <= bound` exclusion that would hide it.
    a = ("def f(xs: list[int]) -> int:\n    total = 0\n    pos = 0\n    for x in xs + xs:\n"
         "        if pos >= 2:\n            total = total + x\n        pos = pos + 1\n    return total")
    b = ("def g(xs: list[int]) -> int:\n    total = 0\n    pos = 0\n    for x in xs + xs:\n"
         "        if pos >= 2:\n            total = total + x + 1\n        pos = pos + 1\n    return total")
    assert _v(a, b, bound=2, int_width=8).status is Status.COUNTEREXAMPLE


def test_int_annotated_function_returning_a_sequence_does_not_crash() -> None:
    # `-> int: return xs` is a type mismatch; the symbolic stage must decline
    # gracefully (not crash merging a SymList with a scalar default).
    a = "def f(xs: list[int]) -> int:\n    return xs"
    b = "def g(xs: list[int]) -> int:\n    return xs"
    assert _v(a, b, bound=2, int_width=8).status in (Status.UNKNOWN, Status.EQUIVALENT)


# --- fifth round (real-Python-grounded multi-agent audit) ------------------

def test_mixed_kind_branch_merge_does_not_crash() -> None:
    # `y = xs` on one branch, `y = 0` on the other: _merge got a SymList and a scalar
    # and dereferenced `.arr` on the scalar. Must not crash.
    a = "def f(xs: list[int]) -> int:\n    if xs:\n        y = xs\n    else:\n        y = 0\n    return 5"
    assert _v(a, a.replace("def f", "def g"), bound=2, int_width=8).status is Status.EQUIVALENT


def test_str_list_branch_merge_is_not_a_false_counterexample() -> None:
    # y is a str on one path and a list on the other; the merge relabeled its kind
    # and mis-evaluated `y == s`, fabricating a divergence. Must not be a false CX.
    a = ("def f(c: bool, s: str, xs: list[int]) -> bool:\n    if c:\n        y = s\n"
         "    else:\n        y = xs\n    return y == s")
    b = "def g(c: bool, s: str, xs: list[int]) -> bool:\n    return c"
    assert _v(a, b, bound=2, int_width=32).status is not Status.COUNTEREXAMPLE


def test_loop_accumulator_kind_change_does_not_crash() -> None:
    a = "def f(xs: list[int]) -> int:\n    s = 0\n    for x in xs:\n        s = [x]\n    return len(s)"
    assert _v(a, a.replace("def f", "def g"), bound=2, int_width=8).status is not Status.COUNTEREXAMPLE


def test_sequence_used_as_scalar_declines_without_crashing() -> None:
    # `-xs` and `xs[xs]` reach _as_bv with a SymList; must decline, not crash in z3.
    for src in ("def f(xs: list[int]) -> int:\n    return -xs",
                "def f(xs: list[int]) -> int:\n    return xs[xs]"):
        assert _v(src, src.replace("def f", "def g"), bound=2, int_width=8).status is not Status.COUNTEREXAMPLE


def test_empty_range_input_is_in_scope() -> None:
    # `range(n)` with n < 0 runs 0 times (empty, in scope); excluding it hid a
    # divergence -> false EQUIVALENT.
    a = "def f(n: int) -> int:\n    s = 0\n    for i in range(n):\n        s = s + 1\n    return s"
    b = ("def g(n: int) -> int:\n    s = 0\n    for i in range(n):\n        s = s + 1\n"
         "    if n < 0:\n        s = 55\n    return s")
    assert _v(a, b, bound=2, int_width=8).status is Status.COUNTEREXAMPLE


def test_near_imax_range_bound_is_in_scope() -> None:
    # range(a, 127) at a=126 runs 1 iteration; `start + bound` overflowed the width
    # and wrongly excluded it -> false EQUIVALENT.
    a = "def f(a: int) -> int:\n    s = 0\n    for i in range(a, 127):\n        s = s + 1\n    return s"
    b = ("def g(a: int) -> int:\n    s = 0\n    for i in range(a, 127):\n        s = s + 1\n"
         "    if a == 126:\n        s = 99\n    return s")
    assert _v(a, b, bound=2, int_width=8).status is Status.COUNTEREXAMPLE


def test_overflowing_loop_bound_stays_out_of_scope() -> None:
    # range(n + 1) at n == imax overflows to a huge range -> out of scope, so the
    # Gauss closed form stays provably equal to the accumulating loop.
    a = "def f(n: int) -> int:\n    assume(n >= 0)\n    return n * (n + 1) // 2"
    b = "def g(n: int) -> int:\n    total = 0\n    for i in range(n + 1):\n        total = total + i\n    return total"
    assert _v(a, b, bound=8, int_width=32).status is Status.EQUIVALENT


def test_falling_off_the_end_is_none_not_an_error() -> None:
    # Falling off the end returns None (a value), distinct from a raised exception.
    falloff = "def f(x: int) -> int:\n    if x > 0:\n        return 1"
    raises = "def g(x: int) -> int:\n    if x > 0:\n        return 1\n    return 1 // 0"
    value = "def g(x: int) -> int:\n    return 5"
    assert _v(falloff, raises).status is Status.COUNTEREXAMPLE                       # None != exception
    assert _v(falloff, value).status is Status.COUNTEREXAMPLE                        # None != 5
    assert _v(falloff, falloff.replace("def f", "def g")).status is Status.EQUIVALENT  # None == None


# --- sixth round (real-Python audit of the round-5 fixes) ------------------

def test_and_or_return_the_operand_value_not_a_bool() -> None:
    # Python `x or 5` returns x or 5 (an operand), not True; the symbolic stage
    # collapsed it to a bool -> false EQUIVALENT.
    assert _v("def f(x: int) -> int:\n    return x or 5",
              "def g(x: int) -> int:\n    return True", bound=2, int_width=8).status is Status.COUNTEREXAMPLE
    assert _v("def f(x: int, y: int) -> int:\n    return x or y",
              "def g(x: int, y: int) -> int:\n    return y or x", bound=2, int_width=8).status is Status.COUNTEREXAMPLE
    # `5 and 3` is 3, not True -> equivalent to a literal 3 (was a false counterexample).
    assert _v("def f() -> int:\n    return 5 and 3",
              "def g() -> int:\n    return 3", bound=2, int_width=8).status is Status.EQUIVALENT
    # and `x or 5` really is `x if x else 5`
    assert _v("def f(x: int) -> int:\n    return x or 5",
              "def g(x: int) -> int:\n    return x if x else 5", bound=2, int_width=8).status is Status.EQUIVALENT


def test_and_or_truth_value_in_boolean_context_is_unchanged() -> None:
    # In a condition the truthiness is what matters, and must stay correct.
    assert _v("def f(x: int) -> int:\n    if x or 5:\n        return 1\n    return 0",
              "def g(x: int) -> int:\n    return 1", bound=2, int_width=8).status is Status.EQUIVALENT


def test_mixed_type_ternary_declines_without_crashing() -> None:
    # `x if x > 0 else "a"` (int/str) and `xs if c else 5` (list/scalar) yield an
    # unmodelable value; must decline, not crash the solver via the _UNDEFINED sentinel.
    for src in ('def f(x: int) -> int:\n    return x if x > 0 else "a"',
                "def f(c: bool, xs: list[int]) -> int:\n    return xs if c else 5",
                "def f(x: int) -> int:\n    return [1] if x > 0 else 2"):
        assert _v(src, src.replace("def f", "def g"), bound=2, int_width=32).status is not Status.COUNTEREXAMPLE


def test_range_bound_at_the_width_edge_is_in_scope() -> None:
    # `range(126, 128)` at width 8 runs 2 iterations (i=126, 127; the exclusive bound
    # 128 == imax+1 is fine). It must be modeled (not wrapped to an empty range): adding
    # 100 twice diverges from x, so it is a real counterexample.
    a = "def f(x: int) -> int:\n    total = x\n    for i in range(126, 128):\n        total = total + 100\n    return total"
    b = "def g(x: int) -> int:\n    return x"
    assert _v(a, b, bound=2, int_width=8).status is Status.COUNTEREXAMPLE
    # the same 2-iteration loop that leaves the value unchanged is proven equivalent.
    assert _v(a.replace("+ 100", "+ 0"), b, bound=2, int_width=8).status is Status.EQUIVALENT


# --- seventh round (audit of the round-6 fixes) ----------------------------

def test_non_int_operand_where_int_required_is_a_type_error() -> None:
    # A str where an int is required is a Python TypeError; the interpreter must not
    # int()-coerce it (int('0')==0) and fabricate a divergence.
    for a, b, iw in [
        ('def f(xs: list[int]) -> int:\n    return xs["0"]', 'def g(xs: list[int]) -> int:\n    return xs["1"]', 32),
        ('def f(s: str) -> int:\n    return -("5" + s)', 'def g(s: str) -> int:\n    return -("6" + s)', 32),
    ]:
        assert _v(a, b, bound=2, int_width=iw).status is not Status.COUNTEREXAMPLE


def test_len_is_fixed_width_wrapped() -> None:
    # len(xs + xs) must wrap like len(xs) + len(xs) (both 2*len, same 2s-complement).
    a = "def f(xs: list[int]) -> int:\n    return len(xs + xs)"
    b = "def g(xs: list[int]) -> int:\n    return len(xs) + len(xs)"
    assert _v(a, b, bound=64, int_width=8).status is Status.EQUIVALENT


def test_candidate_precondition_that_raises_is_a_divergence() -> None:
    # A candidate assume() whose argument raises (assume(xs[0] > 0) on []) is real
    # behavior — the candidate raises where the original returns a value.
    a = "def f(xs: list[int]) -> int:\n    return len(xs)"
    b = "def g(xs: list[int]) -> int:\n    assume(xs[0] > 0)\n    return len(xs)"
    verdict = _v(a, b, bound=2, int_width=8)
    assert verdict.status is Status.COUNTEREXAMPLE
    assert verdict.counterexample.inputs["xs"] == []


def test_loop_bound_at_width_edge_runs_the_real_trip_count() -> None:
    # range(a, a+1) at a=127 runs exactly 1 iteration (i=127); the exclusive bound
    # a+1 == 128 overflowing the width must not make it an empty (0-trip) loop.
    a = "def f(a: int) -> int:\n    s = 0\n    for i in range(a, a + 1):\n        s = s + i\n    return s"
    b = "def g(a: int) -> int:\n    if a == 127:\n        return 0\n    return a"
    verdict = _v(a, b, bound=2, int_width=8)
    assert verdict.status is Status.COUNTEREXAMPLE
    assert verdict.counterexample.inputs["a"] == 127


def test_overflowing_division_loop_bound_stays_out_of_scope() -> None:
    # range(0, x // -1) at x == imin: x//-1 is 128 (a huge trip count), out of scope —
    # not an empty range from a wrapped bound. So the pair is equivalent in scope.
    a = "def f(x: int) -> int:\n    c = 0\n    for i in range(0, x // (0 - 1)):\n        c = c + 1\n    return c"
    b = "def g(x: int) -> int:\n    return (0 - x) if x < 0 else 0"
    assert _v(a, b, bound=2, int_width=8).status is Status.EQUIVALENT


def test_sequence_truthiness_is_nonempty() -> None:
    # `if xs:` / `not xs` used to crash (_as_bool couldn't handle a SymList). A
    # sequence is truthy iff non-empty, exactly like `len(xs) > 0`.
    assert _v("def f(xs: list[int]) -> int:\n    if xs:\n        return 1\n    return 0",
              "def g(xs: list[int]) -> int:\n    if len(xs) > 0:\n        return 1\n    return 0",
              bound=2, int_width=8).status is Status.EQUIVALENT
    assert _v("def f(s: str) -> bool:\n    return not s",
              "def g(s: str) -> bool:\n    return len(s) == 0",
              bound=2, int_width=32).status is Status.EQUIVALENT
    # and a genuine divergence is still caught (empty & length-1 both truthy? no)
    assert _v("def f(xs: list[int]) -> int:\n    if xs:\n        return 1\n    return 0",
              "def g(xs: list[int]) -> int:\n    if len(xs) > 1:\n        return 1\n    return 0",
              bound=2, int_width=8).status is Status.COUNTEREXAMPLE


def test_sequence_repetition_is_not_a_false_counterexample() -> None:
    # `s * 2 == s + s` for every string; the interpreter used to raise on `s * 2`,
    # fabricating a divergence. `*` on sequences is unmodeled -> the pair is UNKNOWN.
    assert _v("def f(s: str) -> str:\n    return s * 2",
              "def g(s: str) -> str:\n    return s + s",
              bound=2, int_width=32).status is not Status.COUNTEREXAMPLE
    assert _v("def f(xs: list[int]) -> list[int]:\n    return xs * 2",
              "def g(xs: list[int]) -> list[int]:\n    return xs + xs",
              bound=2, int_width=8).status is not Status.COUNTEREXAMPLE


def test_nested_list_literal_declines_without_crash_or_false_verdict() -> None:
    # `[xs]` is a list of lists, outside the list[int] model. It must not crash the
    # symbolic stage nor be fabricated as an error (a false counterexample).
    assert _v("def f(xs: list[int]) -> list[int]:\n    return xs + [xs]",
              "def g(xs: list[int]) -> list[int]:\n    return xs + [xs]",
              bound=2, int_width=8).status is not Status.COUNTEREXAMPLE
    assert _v("def f(xs: list[int]) -> int:\n    ys = [xs]\n    return len(ys)",
              "def g(xs: list[int]) -> int:\n    return 1",
              bound=2, int_width=8).status is not Status.COUNTEREXAMPLE
