"""Parser / subset-validation tests for `congruent.ir`."""

from __future__ import annotations

import pytest

from congruent.ir import (
    BinOp,
    BoolOp,
    Compare,
    For,
    ForEach,
    Subscript,
    UnsupportedConstruct,
    parse_condition,
    parse_function,
)


def test_parse_basic_signature() -> None:
    fn = parse_function("def f(x: int, y: bool) -> int:\n    return x", "f")
    assert fn.name == "f"
    assert [(p.name, p.type_name) for p in fn.params] == [("x", "int"), ("y", "bool")]
    assert fn.return_type == "int"


def test_parse_list_int_param() -> None:
    fn = parse_function("def f(xs: list[int]) -> int:\n    return 0", "f")
    assert fn.params[0].type_name == "list[int]"


def test_missing_function_raises_value_error() -> None:
    with pytest.raises(ValueError):
        parse_function("def f(x: int) -> int:\n    return x", "g")


def test_chained_compare_desugars_to_boolop() -> None:
    fn = parse_function("def f(x: int) -> bool:\n    return 0 < x < 10", "f")
    ret = fn.body[0]
    assert isinstance(ret.value, BoolOp)
    assert ret.value.op == "and"
    assert all(isinstance(c, Compare) for c in ret.value.values)


def test_aug_assign_desugars_to_binop() -> None:
    fn = parse_function("def f(x: int) -> int:\n    x += 1\n    return x", "f")
    assign = fn.body[0]
    assert assign.target == "x"
    assert isinstance(assign.value, BinOp) and assign.value.op == "+"


def test_parse_for_range_loop() -> None:
    src = (
        "def f(n: int) -> int:\n"
        "    total = 0\n"
        "    for i in range(n):\n"
        "        total = total + i\n"
        "    return total"
    )
    fn = parse_function(src, "f")
    loop = fn.body[1]
    assert isinstance(loop, For)
    assert loop.var == "i"


def test_parse_precondition() -> None:
    src = "def f(n: int) -> int:\n    assume(n >= 0)\n    return n"
    fn = parse_function(src, "f")
    assert len(fn.preconditions) == 1
    assert fn.preconditions[0].text == "n >= 0"
    assert len(fn.body) == 1  # the assume is peeled off the body


def test_parse_condition_standalone() -> None:
    pc = parse_condition("0 <= x")
    assert pc.text == "0 <= x"


def test_parse_foreach_over_list() -> None:
    src = (
        "def f(xs: list[int]) -> int:\n"
        "    total = 0\n"
        "    for x in xs:\n"
        "        total = total + x\n"
        "    return total"
    )
    fn = parse_function(src, "f")
    assert fn.params[0].type_name == "list[int]"
    assert isinstance(fn.body[1], ForEach)


def test_parse_subscript() -> None:
    fn = parse_function("def f(xs: list[int]) -> int:\n    return xs[0]", "f")
    assert isinstance(fn.body[0].value, Subscript)


def test_parse_return_inside_loop() -> None:
    src = (
        "def f(xs: list[int], t: int) -> bool:\n"
        "    for x in xs:\n"
        "        if x == t:\n"
        "            return True\n"
        "    return False"
    )
    fn = parse_function(src, "f")
    assert isinstance(fn.body[0], ForEach)


@pytest.mark.parametrize(
    "source",
    [
        "def f(x: int) -> int:\n    while x:\n        x = x - 1\n    return x",  # while loop
        "def f(x: int) -> int:\n    x = x + 1\n    assume(x > 0)\n    return x",  # non-leading assume
        "def f(x: int) -> int:\n    break\n    return x",  # break outside a loop
        "def f(x: int) -> int:\n    continue\n    return x",  # continue outside a loop
        "def f(x: int) -> int:\n    for i in range(x):\n        pass\n    else:\n        pass\n    return x",  # for/else
        "def f(x: int) -> int:\n    for i in range(0, x, 2):\n        x = x + 1\n    return x",  # range step
        "def f(x: float) -> float:\n    return x",  # float type
        "def f(x: int) -> int:\n    import os\n    return x",  # import
        "def f(x: int) -> int:\n    return x / 2",  # true division (-> float)
        "def f(x: int) -> int:\n    return x ** 2",  # exponentiation
        "def f(x: int):\n    return x",  # missing return annotation
        "def f(x) -> int:\n    return x",  # missing param annotation
        "def f(x: int) -> int:\n    return",  # bare return
        "def f(x: int) -> str:\n    return 'a'",  # string literal / type
    ],
)
def test_unsupported_constructs_raise(source: str) -> None:
    with pytest.raises(UnsupportedConstruct):
        parse_function(source, "f")
