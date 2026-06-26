"""Symbolic interpreter — Stage 2 core: IR -> Z3 expressions.

This is path (A) from the foundational doc §3: a from-scratch mini symbolic
interpreter. For the M1 (loop-free) subset it lowers each function to a *single*
Z3 expression over fresh symbolic inputs, encoding branches as `ite` and
threading early `return`s through a continuation. The solver layer then asserts
the two functions' output expressions differ.

**Semantics must mirror `difftest`'s concrete interpreter exactly**, or M0 and
M1 could disagree:
    - integers are `int_width`-bit bitvectors (arithmetic wraps mod 2**width),
    - `//` and `%` are Python floor division / modulo (not C-style truncation),
    - signed comparisons.

Anything that cannot be modeled soundly yet (loops, list params, division by a
non-constant or zero divisor) raises `UnsupportedForProof`, and the orchestrator
falls back to the differential verdict rather than risk a false `EQUIVALENT`.
"""

from __future__ import annotations

import z3

from congruent import ir
from congruent.ir import Function


class UnsupportedForProof(Exception):
    """The symbolic stage cannot soundly model this function (yet)."""


# A continuation: given the current environment, produce the return-value expr
# for "the rest of the function" from this program point onward.
_Env = dict[str, z3.ExprRef]


def make_input_symbols(params: list[ir.Param], int_width: int) -> list[z3.ExprRef]:
    """Create one fresh Z3 symbol per parameter (shared across both functions)."""
    symbols: list[z3.ExprRef] = []
    for i, param in enumerate(params):
        if param.type_name == "int":
            symbols.append(z3.BitVec(f"in{i}", int_width))
        elif param.type_name == "bool":
            symbols.append(z3.Bool(f"in{i}"))
        else:
            raise UnsupportedForProof(f"parameter type {param.type_name!r} not modeled yet (M2)")
    return symbols


def summarize(
    function: Function, input_symbols: list[z3.ExprRef], int_width: int
) -> z3.ExprRef:
    """Lower `function` to a single Z3 expression for its return value.

    `input_symbols` are bound positionally to the function's parameters, so two
    functions can be summarized over the *same* symbols for an equivalence query.
    """
    env: _Env = {p.name: sym for p, sym in zip(function.params, input_symbols)}

    def fell_off_end(_: _Env) -> z3.ExprRef:
        raise UnsupportedForProof(f"{function.name}: a path may fall off the end without returning")

    return _exec_stmts(function.body, env, int_width, fell_off_end)


# --- statement execution (continuation-passing) ----------------------------

def _exec_stmts(stmts, env: _Env, w: int, k) -> z3.ExprRef:  # k: _Env -> ExprRef
    if not stmts:
        return k(env)
    head, rest = stmts[0], stmts[1:]

    if isinstance(head, ir.Return):
        return _eval(head.value, env, w)

    if isinstance(head, ir.Assign):
        new_env = dict(env)
        new_env[head.target] = _eval(head.value, env, w)
        return _exec_stmts(rest, new_env, w, k)

    if isinstance(head, ir.If):
        cond = _as_bool(_eval(head.test, env, w))

        def k_rest(env_after: _Env) -> z3.ExprRef:
            return _exec_stmts(rest, env_after, w, k)

        then_val = _exec_stmts(head.body, env, w, k_rest)
        else_val = _exec_stmts(head.orelse, env, w, k_rest)
        return _merge(cond, then_val, else_val, w)

    raise AssertionError(f"unhandled statement node: {head!r}")


# --- expression evaluation -------------------------------------------------

def _eval(node: ir.Expr, env: _Env, w: int) -> z3.ExprRef:
    if isinstance(node, ir.Name):
        if node.id not in env:
            raise UnsupportedForProof(f"reference to unbound name {node.id!r}")
        return env[node.id]

    if isinstance(node, ir.Const):
        if node.type_name == "bool":
            return z3.BoolVal(bool(node.value))
        return z3.BitVecVal(node.value, w)  # z3 reduces mod 2**w

    if isinstance(node, ir.BinOp):
        return _eval_binop(node, env, w)

    if isinstance(node, ir.UnaryOp):
        operand = _eval(node.operand, env, w)
        if node.op == "-":
            return -_as_bv(operand, w)
        return z3.Not(_as_bool(operand))

    if isinstance(node, ir.Compare):
        return _eval_compare(node, env, w)

    if isinstance(node, ir.BoolOp):
        parts = [_as_bool(_eval(v, env, w)) for v in node.values]
        return z3.And(parts) if node.op == "and" else z3.Or(parts)

    if isinstance(node, ir.IfExp):
        cond = _as_bool(_eval(node.test, env, w))
        return _merge(cond, _eval(node.body, env, w), _eval(node.orelse, env, w), w)

    raise AssertionError(f"unhandled expression node: {node!r}")


def _eval_binop(node: ir.BinOp, env: _Env, w: int) -> z3.ExprRef:
    left = _as_bv(_eval(node.left, env, w), w)
    right = _as_bv(_eval(node.right, env, w), w)
    op = node.op
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if op in ("//", "%"):
        if not (isinstance(node.right, ir.Const) and node.right.type_name == "int" and node.right.value != 0):
            raise UnsupportedForProof(
                "division/modulo by a non-constant or zero divisor is not modeled yet"
            )
        return _floordiv(left, right) if op == "//" else _floormod(left, right)
    raise AssertionError(f"unhandled binop {op!r}")


def _eval_compare(node: ir.Compare, env: _Env, w: int) -> z3.ExprRef:
    left = _eval(node.left, env, w)
    right = _eval(node.right, env, w)
    op = node.op
    if op == "==" or op == "!=":
        if z3.is_bool(left) and z3.is_bool(right):
            return left == right if op == "==" else left != right
        left, right = _as_bv(left, w), _as_bv(right, w)
        return left == right if op == "==" else left != right
    # ordering: signed bitvector comparison (z3 overloads < <= > >= as signed)
    left, right = _as_bv(left, w), _as_bv(right, w)
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    return left >= right  # ">="


# --- Python-faithful fixed-width arithmetic --------------------------------

def _floordiv(a: z3.ExprRef, b: z3.ExprRef) -> z3.ExprRef:
    """Floor division matching Python `//` (b is a non-zero constant)."""
    q = a / b  # z3: signed division, truncates toward zero
    r = a - q * b
    zero = z3.BitVecVal(0, a.size())
    one = z3.BitVecVal(1, a.size())
    # adjust toward -inf when the remainder is nonzero and signs of r and b differ
    needs_adjust = z3.And(r != zero, z3.Xor(r < zero, b < zero))
    return z3.If(needs_adjust, q - one, q)


def _floormod(a: z3.ExprRef, b: z3.ExprRef) -> z3.ExprRef:
    """Modulo matching Python `%` (result takes the sign of the divisor)."""
    return a - _floordiv(a, b) * b


# --- sort coercions / merging ----------------------------------------------

def _as_bool(e: z3.ExprRef) -> z3.ExprRef:
    if z3.is_bool(e):
        return e
    return e != z3.BitVecVal(0, e.size())  # truthiness of an int: != 0


def _as_bv(e: z3.ExprRef, w: int) -> z3.ExprRef:
    if z3.is_bv(e):
        return e
    return z3.If(e, z3.BitVecVal(1, w), z3.BitVecVal(0, w))  # bool -> 0/1


def _merge(cond: z3.ExprRef, then_val: z3.ExprRef, else_val: z3.ExprRef, w: int) -> z3.ExprRef:
    """`ite` over two branch results, coercing to a common sort if they differ."""
    if z3.is_bool(then_val) and z3.is_bool(else_val):
        return z3.If(cond, then_val, else_val)
    return z3.If(cond, _as_bv(then_val, w), _as_bv(else_val, w))
