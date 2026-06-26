"""AST -> normalized typed IR (pipeline stage 0).

Both the differential tester and (at M1) the symbolic engine consume this IR
rather than raw `ast` nodes, so the rules of the supported v1 subset live in
exactly one place.

Supported subset (v1):
    - `def` with type-annotated positional parameters (int, bool, list[int])
    - `return <expr>`
    - assignment to a name: `x = <expr>` (and augmented `x += <expr>`)
    - `if` / `elif` / `else`
    - conditional expressions: `a if c else b`
    - integer arithmetic: + - * // %   (and unary -)
    - comparisons: < <= > >= == !=   (including chained: a < b < c)
    - boolean logic: and / or / not
    - integer and boolean literals
    - `for <var> in range(...)` bounded loops (M2; no `return` inside the loop)

Out of scope (raise `UnsupportedConstruct` loudly — never ignored):
    while, recursion-via-call, floats, strings, I/O, global mutation,
    list/attribute/subscript assignment, comprehensions, exceptions,
    `return`/`break`/`continue` inside a loop. Arrays arrive later in M2 (see
    ROADMAP.md). Refusing to model a construct is what keeps verdicts honest.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Union


class UnsupportedConstruct(Exception):
    """Raised when source uses a construct outside the supported v1 subset."""


# --- Expressions -----------------------------------------------------------

@dataclass(frozen=True)
class Name:
    id: str


@dataclass(frozen=True)
class Const:
    value: int | bool
    type_name: str  # "int" | "bool"


@dataclass(frozen=True)
class BinOp:
    op: str  # + - * // %
    left: "Expr"
    right: "Expr"


@dataclass(frozen=True)
class UnaryOp:
    op: str  # - | not
    operand: "Expr"


@dataclass(frozen=True)
class Compare:
    op: str  # < <= > >= == !=
    left: "Expr"
    right: "Expr"


@dataclass(frozen=True)
class BoolOp:
    op: str  # and | or
    values: tuple["Expr", ...]


@dataclass(frozen=True)
class IfExp:
    test: "Expr"
    body: "Expr"
    orelse: "Expr"


Expr = Union[Name, Const, BinOp, UnaryOp, Compare, BoolOp, IfExp]


# --- Statements ------------------------------------------------------------

@dataclass(frozen=True)
class Return:
    value: Expr


@dataclass(frozen=True)
class Assign:
    target: str
    value: Expr


@dataclass(frozen=True)
class If:
    test: Expr
    body: tuple["Stmt", ...]
    orelse: tuple["Stmt", ...]


@dataclass(frozen=True)
class For:
    """`for <var> in range(<start>, <stop>)` — a bounded counting loop.

    `range(stop)` is normalized to start = literal 0. The loop is unrolled to
    `--bound` iterations (symbolic) / capped at `--bound` (concrete); inputs
    that would drive more iterations are out of scope for the verdict.
    """

    var: str
    start: Expr
    stop: Expr
    body: tuple["Stmt", ...]


Stmt = Union[Return, Assign, If, For]


@dataclass(frozen=True)
class Param:
    name: str
    type_name: str  # "int" | "bool" | "list[int]"


@dataclass
class Function:
    name: str
    params: list[Param]
    return_type: str
    body: tuple[Stmt, ...]


# --- Parsing / lowering ----------------------------------------------------

_BINOPS: dict[type, str] = {
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
    ast.FloorDiv: "//",
    ast.Mod: "%",
}
_CMPOPS: dict[type, str] = {
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
    ast.Eq: "==",
    ast.NotEq: "!=",
}


def parse_function(source: str, name: str) -> Function:
    """Parse `source` and return the IR `Function` named `name`.

    Raises:
        UnsupportedConstruct: the function uses a construct outside the v1 subset.
        ValueError: no function named `name` is found in `source`.
    """
    module = ast.parse(source)
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return _lower_function(node)
    raise ValueError(f"no function named {name!r} found in source")


def _lower_function(node: ast.FunctionDef) -> Function:
    if node.decorator_list:
        raise UnsupportedConstruct(f"{node.name}: decorators are not supported")
    a = node.args
    if a.vararg or a.kwarg or a.kwonlyargs:
        raise UnsupportedConstruct(f"{node.name}: only positional parameters are supported")

    params: list[Param] = []
    for arg in [*a.posonlyargs, *a.args]:
        if arg.annotation is None:
            raise UnsupportedConstruct(f"{node.name}: parameter {arg.arg!r} needs a type annotation")
        params.append(Param(arg.arg, _normalize_type(arg.annotation)))

    if node.returns is None:
        raise UnsupportedConstruct(f"{node.name}: a return type annotation is required")
    return_type = _normalize_type(node.returns)

    body = _lower_block(_strip_docstring(node.body))
    return Function(node.name, params, return_type, body)


def _strip_docstring(stmts: list[ast.stmt]) -> list[ast.stmt]:
    if (
        stmts
        and isinstance(stmts[0], ast.Expr)
        and isinstance(stmts[0].value, ast.Constant)
        and isinstance(stmts[0].value.value, str)
    ):
        return stmts[1:]
    return stmts


def _normalize_type(node: ast.expr) -> str:
    if isinstance(node, ast.Name) and node.id in {"int", "bool"}:
        return node.id
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id in {"list", "List"}
        and isinstance(node.slice, ast.Name)
        and node.slice.id == "int"
    ):
        return "list[int]"
    raise UnsupportedConstruct(f"unsupported type annotation: {ast.dump(node)}")


def _lower_block(stmts: list[ast.stmt]) -> tuple[Stmt, ...]:
    return tuple(_lower_stmt(s) for s in stmts)


def _lower_stmt(node: ast.stmt) -> Stmt:
    if isinstance(node, ast.Return):
        if node.value is None:
            raise UnsupportedConstruct("bare `return` is not supported; return a value")
        return Return(_lower_expr(node.value))

    if isinstance(node, ast.Assign):
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            raise UnsupportedConstruct("only single-name assignment is supported")
        return Assign(node.targets[0].id, _lower_expr(node.value))

    if isinstance(node, ast.AugAssign):
        if not isinstance(node.target, ast.Name):
            raise UnsupportedConstruct("only single-name augmented assignment is supported")
        op = _BINOPS.get(type(node.op))
        if op is None:
            raise UnsupportedConstruct(f"unsupported augmented operator: {type(node.op).__name__}")
        target = node.target.id
        return Assign(target, BinOp(op, Name(target), _lower_expr(node.value)))

    if isinstance(node, ast.If):
        return If(
            _lower_expr(node.test),
            _lower_block(node.body),
            _lower_block(node.orelse),
        )

    if isinstance(node, ast.For):
        return _lower_for(node)

    if isinstance(node, ast.Pass):
        # harmless no-op; lower to an empty if-false would be silly — drop it.
        # Represent as an If with empty branches so the type stays simple.
        return If(Const(False, "bool"), (), ())

    raise UnsupportedConstruct(f"unsupported statement: {type(node).__name__}")


def _lower_for(node: ast.For) -> For:
    if node.orelse:
        raise UnsupportedConstruct("for/else is not supported")
    if not isinstance(node.target, ast.Name):
        raise UnsupportedConstruct("loop target must be a single name")
    if not (
        isinstance(node.iter, ast.Call)
        and isinstance(node.iter.func, ast.Name)
        and node.iter.func.id == "range"
    ):
        raise UnsupportedConstruct("loops must iterate over range(...)")
    args = node.iter.args
    if node.iter.keywords or not 1 <= len(args) <= 2:
        raise UnsupportedConstruct("only range(stop) and range(start, stop) are supported")
    if len(args) == 1:
        start: Expr = Const(0, "int")
        stop = _lower_expr(args[0])
    else:
        start = _lower_expr(args[0])
        stop = _lower_expr(args[1])

    body = _lower_block(node.body)
    if _contains_return(body):
        raise UnsupportedConstruct("`return` inside a loop is not supported yet")
    return For(node.target.id, start, stop, body)


def _contains_return(stmts: tuple[Stmt, ...]) -> bool:
    for stmt in stmts:
        if isinstance(stmt, Return):
            return True
        if isinstance(stmt, If) and (_contains_return(stmt.body) or _contains_return(stmt.orelse)):
            return True
        if isinstance(stmt, For) and _contains_return(stmt.body):
            return True
    return False


def _lower_expr(node: ast.expr) -> Expr:
    if isinstance(node, ast.Name):
        return Name(node.id)

    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return Const(node.value, "bool")
        if isinstance(node.value, int):
            return Const(node.value, "int")
        raise UnsupportedConstruct(f"unsupported literal: {node.value!r}")

    if isinstance(node, ast.BinOp):
        op = _BINOPS.get(type(node.op))
        if op is None:
            raise UnsupportedConstruct(f"unsupported operator: {type(node.op).__name__}")
        return BinOp(op, _lower_expr(node.left), _lower_expr(node.right))

    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.USub):
            return UnaryOp("-", _lower_expr(node.operand))
        if isinstance(node.op, ast.Not):
            return UnaryOp("not", _lower_expr(node.operand))
        raise UnsupportedConstruct(f"unsupported unary operator: {type(node.op).__name__}")

    if isinstance(node, ast.BoolOp):
        op = "and" if isinstance(node.op, ast.And) else "or"
        return BoolOp(op, tuple(_lower_expr(v) for v in node.values))

    if isinstance(node, ast.Compare):
        return _lower_compare(node)

    if isinstance(node, ast.IfExp):
        return IfExp(_lower_expr(node.test), _lower_expr(node.body), _lower_expr(node.orelse))

    raise UnsupportedConstruct(f"unsupported expression: {type(node).__name__}")


def _lower_compare(node: ast.Compare) -> Expr:
    """Lower a comparison, desugaring chained `a < b < c` to `(a < b) and (b < c)`."""
    operands = [node.left, *node.comparators]
    parts: list[Expr] = []
    for i, op_node in enumerate(node.ops):
        op = _CMPOPS.get(type(op_node))
        if op is None:
            raise UnsupportedConstruct(f"unsupported comparison: {type(op_node).__name__}")
        parts.append(Compare(op, _lower_expr(operands[i]), _lower_expr(operands[i + 1])))
    if len(parts) == 1:
        return parts[0]
    return BoolOp("and", tuple(parts))
