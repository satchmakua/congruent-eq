"""C front end: parse a C function into Congruent's IR.

C's `int` is already fixed-width, so it maps directly onto the bitvector model
and the whole existing engine (difftest + symbolic) is reused unchanged. The
supported C subset mirrors the Python one:

    - functions over `int` / `_Bool` scalar parameters, returning `int`/`_Bool`
    - `return`, `if`/`else`, blocks
    - assignment, compound assignment (`+=` ...), and `int x = e;` declarations
    - canonical counting loops: `for (i = lo; i < hi; i++)` (and `i += 1`, `<=`)
    - `break` / `continue`
    - arithmetic `+ - * / %` (C truncating division), comparisons, `&& || !`,
      unary `-`, and the ternary `c ? a : b`

Out of scope (raise `UnsupportedConstruct`): pointers, arrays, `while`, bitwise
operators, casts, function calls, floats. The honesty is the same as for Python.

Division note: C `/` and `%` truncate toward zero, so they lower to the IR's
`c/` / `c%` ops (distinct from Python's floor `//` / `%`).
"""

from __future__ import annotations

import re

from pycparser import CParser, c_ast

from congruent import ir
from congruent.ir import (
    Assign,
    BinOp,
    BoolOp,
    Break,
    Compare,
    Const,
    Continue,
    For,
    Function,
    IfExp,
    Name,
    Param,
    Return,
    UnaryOp,
    UnsupportedConstruct,
)

_C_TYPES = {("int",): "int", ("_Bool",): "bool", ("signed", "int"): "int"}

_ARITH = {"+": "+", "-": "-", "*": "*", "/": "c/", "%": "c%"}
_CMP = {"<", "<=", ">", ">=", "==", "!="}


def _preprocess(source: str) -> str:
    """Strip comments and preprocessor directives (pycparser wants preprocessed C)."""
    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.DOTALL)  # block comments
    source = re.sub(r"//[^\n]*", "", source)  # line comments
    source = re.sub(r"(?m)^[ \t]*#.*$", "", source)  # #include / #define / ...
    return source


def parse_c_function(source: str, name: str) -> Function:
    """Parse `source` (C) and return the IR `Function` named `name`."""
    try:
        unit = CParser().parse(_preprocess(source))
    except Exception as exc:  # noqa: BLE001 — pycparser raises bare ParseError
        raise UnsupportedConstruct(f"C parse error: {exc}") from exc
    for node in unit.ext:
        if isinstance(node, c_ast.FuncDef) and node.decl.name == name:
            return _lower_function(node)
    raise ValueError(f"no function named {name!r} found in source")


def _lower_function(node: c_ast.FuncDef) -> Function:
    decl = node.decl.type  # FuncDecl
    params: list[Param] = []
    args = decl.args.params if decl.args else []
    for arg in args:
        if isinstance(arg, c_ast.EllipsisParam) or arg.name is None:
            raise UnsupportedConstruct("variadic / unnamed parameters are not supported")
        params.append(Param(arg.name, _type_of(arg.type)))
    return_type = _type_of(decl.type)
    body = _lower_block(node.body)
    return Function(node.decl.name, params, return_type, body)


def _type_of(node: c_ast.Node) -> str:
    if not isinstance(node, c_ast.TypeDecl) or not isinstance(node.type, c_ast.IdentifierType):
        raise UnsupportedConstruct("only scalar int / _Bool types are supported")
    key = tuple(node.type.names)
    if key not in _C_TYPES:
        raise UnsupportedConstruct(f"unsupported C type: {' '.join(node.type.names)}")
    return _C_TYPES[key]


def _lower_block(node: c_ast.Node) -> tuple[ir.Stmt, ...]:
    """Lower a Compound (or a single statement) to a tuple of IR statements."""
    if node is None:
        return ()
    items = node.block_items or [] if isinstance(node, c_ast.Compound) else [node]
    out: list[ir.Stmt] = []
    for item in items:
        lowered = _lower_stmt(item)
        if lowered is not None:
            out.append(lowered)
    return tuple(out)


def _lower_stmt(node: c_ast.Node) -> ir.Stmt | None:
    if isinstance(node, c_ast.Return):
        if node.expr is None:
            raise UnsupportedConstruct("bare `return;` is not supported; return a value")
        return Return(_lower_expr(node.expr))

    if isinstance(node, c_ast.Decl):
        if node.init is None:
            return None  # `int t;` — a declaration with no effect until assigned
        return Assign(node.name, _lower_expr(node.init))

    if isinstance(node, c_ast.Assignment):
        if not isinstance(node.lvalue, c_ast.ID):
            raise UnsupportedConstruct("only assignment to a simple variable is supported")
        target = node.lvalue.name
        if node.op == "=":
            return Assign(target, _lower_expr(node.rvalue))
        arith = node.op[:-1]  # strip the '=' from '+=', '-=', ...
        if arith not in _ARITH:
            raise UnsupportedConstruct(f"unsupported compound assignment: {node.op}")
        return Assign(target, BinOp(_ARITH[arith], Name(target), _lower_expr(node.rvalue)))

    if isinstance(node, c_ast.If):
        return ir.If(_lower_expr(node.cond), _lower_block(node.iftrue), _lower_block(node.iffalse))

    if isinstance(node, c_ast.For):
        return _lower_for(node)

    if isinstance(node, c_ast.Break):
        return Break()

    if isinstance(node, c_ast.Continue):
        return Continue()

    if isinstance(node, c_ast.Compound):
        raise UnsupportedConstruct("nested blocks are not supported")

    if isinstance(node, c_ast.EmptyStatement):
        return None

    raise UnsupportedConstruct(f"unsupported C statement: {type(node).__name__}")


def _lower_for(node: c_ast.For) -> For:
    """Map a canonical counting loop `for (i = lo; i < hi; i++)` to ir.For."""
    var, start = _loop_init(node.init)
    stop = _loop_cond(node.cond, var)
    _check_loop_step(node.next, var)
    body = _lower_block(node.stmt)
    return For(var, start, stop, body)


def _loop_init(init: c_ast.Node) -> tuple[str, ir.Expr]:
    if isinstance(init, c_ast.DeclList) and len(init.decls) == 1:
        decl = init.decls[0]
        if decl.init is None:
            raise UnsupportedConstruct("loop counter must be initialized")
        return decl.name, _lower_expr(decl.init)
    if isinstance(init, c_ast.Assignment) and init.op == "=" and isinstance(init.lvalue, c_ast.ID):
        return init.lvalue.name, _lower_expr(init.rvalue)
    raise UnsupportedConstruct("loop init must be `i = lo` or `int i = lo`")


def _loop_cond(cond: c_ast.Node, var: str) -> ir.Expr:
    if not (isinstance(cond, c_ast.BinaryOp) and cond.op in ("<", "<=")):
        raise UnsupportedConstruct("loop condition must be `i < hi` or `i <= hi`")
    if not (isinstance(cond.left, c_ast.ID) and cond.left.name == var):
        raise UnsupportedConstruct("loop condition must test the loop counter")
    stop = _lower_expr(cond.right)
    if cond.op == "<=":
        stop = BinOp("+", stop, Const(1, "int"))
    return stop


def _check_loop_step(step: c_ast.Node, var: str) -> None:
    """Require the step to advance the counter by exactly 1."""
    if isinstance(step, c_ast.UnaryOp) and step.op in ("p++", "++") and _is_var(step.expr, var):
        return
    if isinstance(step, c_ast.Assignment) and _is_var(step.lvalue, var):
        if step.op == "+=" and _is_const(step.rvalue, 1):
            return
        if step.op == "=" and isinstance(step.rvalue, c_ast.BinaryOp) and step.rvalue.op == "+":
            if _is_var(step.rvalue.left, var) and _is_const(step.rvalue.right, 1):
                return
    raise UnsupportedConstruct("loop step must increment the counter by 1")


def _is_var(node: c_ast.Node, var: str) -> bool:
    return isinstance(node, c_ast.ID) and node.name == var


def _is_const(node: c_ast.Node, value: int) -> bool:
    return isinstance(node, c_ast.Constant) and _const_value(node) == value


def _const_value(node: c_ast.Constant) -> int:
    if node.type == "char":
        return ord(node.value.strip("'").encode().decode("unicode_escape"))
    return int(node.value.rstrip("uUlL"), 0)  # handles 0x.., 0.., decimal


def _lower_expr(node: c_ast.Node) -> ir.Expr:
    if isinstance(node, c_ast.ID):
        return Name(node.name)

    if isinstance(node, c_ast.Constant):
        if node.type not in ("int", "char"):
            raise UnsupportedConstruct(f"unsupported C literal type: {node.type}")
        return Const(_const_value(node), "int")

    if isinstance(node, c_ast.BinaryOp):
        if node.op in _ARITH:
            return BinOp(_ARITH[node.op], _lower_expr(node.left), _lower_expr(node.right))
        if node.op in _CMP:
            return Compare(node.op, _lower_expr(node.left), _lower_expr(node.right))
        if node.op in ("&&", "||"):
            op = "and" if node.op == "&&" else "or"
            return BoolOp(op, (_lower_expr(node.left), _lower_expr(node.right)))
        raise UnsupportedConstruct(f"unsupported C operator: {node.op}")

    if isinstance(node, c_ast.UnaryOp):
        if node.op == "-":
            return UnaryOp("-", _lower_expr(node.expr))
        if node.op == "!":
            return UnaryOp("not", _lower_expr(node.expr))
        if node.op == "+":
            return _lower_expr(node.expr)
        raise UnsupportedConstruct(f"unsupported C unary operator: {node.op}")

    if isinstance(node, c_ast.TernaryOp):
        return IfExp(_lower_expr(node.cond), _lower_expr(node.iftrue), _lower_expr(node.iffalse))

    raise UnsupportedConstruct(f"unsupported C expression: {type(node).__name__}")
