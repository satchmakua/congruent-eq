"""Symbolic interpreter — Stage 2 core: IR -> Z3 expressions.

This is path (A) from the foundational doc §3: a from-scratch mini symbolic
interpreter. It lowers a function to a single Z3 expression over fresh symbolic
inputs. Branches and early `return`s are handled by continuation-passing path
merging; bounded `for` loops are unrolled to `--bound` iterations.

**Semantics must mirror `difftest`'s concrete interpreter exactly**, or M0/M1
and M2 could disagree:
    - integers are `int_width`-bit bitvectors (arithmetic wraps mod 2**width),
    - `//` and `%` are Python floor division / modulo (not C truncation),
    - signed comparisons.

**Bounded model checking.** A loop is unrolled `bound` times; iteration k only
takes effect under the guard `start + k < stop`. We also record an *in-bound
assumption* — that the loop runs 0..`bound` times and its index window does not
wrap — so the equivalence query is only asked where every loop stays within the
bound. That is what makes a loop verdict an honest "EQUIVALENT up to bound N".

Anything not soundly modeled (loop bodies that `return`, division by a
non-constant/zero divisor, list params, variables first assigned inside a loop)
raises `UnsupportedForProof`; the orchestrator then falls back to the
differential verdict rather than risk a false `EQUIVALENT`.
"""

from __future__ import annotations

from dataclasses import dataclass

import z3

from congruent import ir
from congruent.ir import Function

_Env = dict[str, z3.ExprRef]


class UnsupportedForProof(Exception):
    """The symbolic stage cannot soundly model this function (yet)."""


@dataclass
class Summary:
    """The symbolic result of one function."""

    output: z3.ExprRef
    assumptions: list[z3.BoolRef]  # in-bound conditions accumulated from loops
    unrolled: bool                 # whether any loop was unrolled (verdict is bounded)


class _Ctx:
    __slots__ = ("w", "bound", "assumptions", "unrolled")

    def __init__(self, width: int, bound: int) -> None:
        self.w = width
        self.bound = bound
        self.assumptions: list[z3.BoolRef] = []
        self.unrolled = False


def make_input_symbols(params: list[ir.Param], int_width: int) -> list[z3.ExprRef]:
    """Create one fresh Z3 symbol per parameter (shared across both functions)."""
    symbols: list[z3.ExprRef] = []
    for i, param in enumerate(params):
        if param.type_name == "int":
            symbols.append(z3.BitVec(f"in{i}", int_width))
        elif param.type_name == "bool":
            symbols.append(z3.Bool(f"in{i}"))
        else:
            raise UnsupportedForProof(f"parameter type {param.type_name!r} not modeled yet")
    return symbols


def lower_preconditions(
    function: Function, input_symbols: list[z3.ExprRef], int_width: int
) -> list[z3.BoolRef]:
    """Lower a function's `assume(...)` preconditions to Z3 boolean constraints."""
    env: _Env = {p.name: sym for p, sym in zip(function.params, input_symbols)}
    ctx = _Ctx(int_width, 0)  # bound is irrelevant for plain expressions
    return [_as_bool(_eval(pc.expr, env, ctx)) for pc in function.preconditions]


def summarize(
    function: Function, input_symbols: list[z3.ExprRef], int_width: int, bound: int
) -> Summary:
    """Lower `function` to a `Summary` over the (positionally bound) inputs."""
    env: _Env = {p.name: sym for p, sym in zip(function.params, input_symbols)}
    ctx = _Ctx(int_width, bound)

    def fell_off_end(_: _Env) -> z3.ExprRef:
        raise UnsupportedForProof(f"{function.name}: a path may fall off the end without returning")

    output = _exec_stmts(function.body, env, ctx, fell_off_end)
    return Summary(output, ctx.assumptions, ctx.unrolled)


# --- statement execution (continuation-passing; `return` allowed here) ------

def _exec_stmts(stmts, env: _Env, ctx: _Ctx, k) -> z3.ExprRef:  # k: _Env -> ExprRef
    if not stmts:
        return k(env)
    head, rest = stmts[0], stmts[1:]

    if isinstance(head, ir.Return):
        return _eval(head.value, env, ctx)

    if isinstance(head, ir.Assign):
        new_env = dict(env)
        new_env[head.target] = _eval(head.value, env, ctx)
        return _exec_stmts(rest, new_env, ctx, k)

    if isinstance(head, ir.If):
        cond = _as_bool(_eval(head.test, env, ctx))

        def k_rest(env_after: _Env) -> z3.ExprRef:
            return _exec_stmts(rest, env_after, ctx, k)

        then_val = _exec_stmts(head.body, env, ctx, k_rest)
        else_val = _exec_stmts(head.orelse, env, ctx, k_rest)
        return _merge(cond, then_val, else_val, ctx.w)

    if isinstance(head, ir.For):
        env_after = _unroll_for(head, env, ctx)
        return _exec_stmts(rest, env_after, ctx, k)

    raise AssertionError(f"unhandled statement node: {head!r}")


# --- loop unrolling (env transformer; `return` inside the loop is rejected) --

def _unroll_for(loop: ir.For, env: _Env, ctx: _Ctx) -> _Env:
    ctx.unrolled = True
    start = _as_bv(_eval(loop.start, env, ctx), ctx.w)
    stop = _as_bv(_eval(loop.stop, env, ctx), ctx.w)

    # Variables written in the loop must be initialized before it, so every
    # merge below has a well-defined "iteration skipped" value.
    written = _assigned_names(loop.body) - {loop.var}
    missing = written - set(env)
    if missing:
        raise UnsupportedForProof(
            f"variable(s) {sorted(missing)} assigned in a loop but not initialized before it"
        )

    cur = env
    for k in range(ctx.bound):
        idx = start + z3.BitVecVal(k, ctx.w)
        guard = idx < stop  # signed: iteration k runs iff start + k < stop
        body_env = dict(cur)
        body_env[loop.var] = idx
        after = _exec_block_env(loop.body, body_env, ctx)
        after.pop(loop.var, None)  # the loop variable does not escape
        cur = {name: _merge(guard, after[name], cur[name], ctx.w) for name in cur}

    # In-bound assumption: the loop runs between 0 and `bound` times AND its
    # index window does not wrap — i.e. stop in [start, start + bound] with no
    # overflow. The no-wrap part matters: without it, a loop bound expression
    # that overflows in fixed width (e.g. range(n + 1) at n = INT_MAX, which
    # wraps to an empty range) would be falsely treated as in-bounds.
    end = start + z3.BitVecVal(ctx.bound, ctx.w)
    ctx.assumptions.append(z3.And(start <= end, start <= stop, stop <= end))
    return cur


def _exec_block_env(stmts, env: _Env, ctx: _Ctx) -> _Env:
    """Execute a return-free block as an environment transformer."""
    cur = env
    for stmt in stmts:
        if isinstance(stmt, ir.Assign):
            cur = {**cur, stmt.target: _eval(stmt.value, cur, ctx)}
        elif isinstance(stmt, ir.If):
            cond = _as_bool(_eval(stmt.test, cur, ctx))
            then_env = _exec_block_env(stmt.body, cur, ctx)
            else_env = _exec_block_env(stmt.orelse, cur, ctx)
            cur = {name: _merge(cond, then_env[name], else_env[name], ctx.w) for name in cur}
        elif isinstance(stmt, ir.For):
            cur = _unroll_for(stmt, cur, ctx)
        else:  # ir.Return — blocked by the parser, but guard anyway
            raise UnsupportedForProof("`return` inside a loop is not supported")
    return cur


def _assigned_names(stmts) -> set[str]:
    names: set[str] = set()
    for stmt in stmts:
        if isinstance(stmt, ir.Assign):
            names.add(stmt.target)
        elif isinstance(stmt, ir.If):
            names |= _assigned_names(stmt.body) | _assigned_names(stmt.orelse)
        elif isinstance(stmt, ir.For):
            names |= _assigned_names(stmt.body) - {stmt.var}
    return names


# --- expression evaluation -------------------------------------------------

def _eval(node: ir.Expr, env: _Env, ctx: _Ctx) -> z3.ExprRef:
    if isinstance(node, ir.Name):
        if node.id not in env:
            raise UnsupportedForProof(f"reference to unbound name {node.id!r}")
        return env[node.id]

    if isinstance(node, ir.Const):
        if node.type_name == "bool":
            return z3.BoolVal(bool(node.value))
        return z3.BitVecVal(node.value, ctx.w)  # z3 reduces mod 2**w

    if isinstance(node, ir.BinOp):
        return _eval_binop(node, env, ctx)

    if isinstance(node, ir.UnaryOp):
        operand = _eval(node.operand, env, ctx)
        if node.op == "-":
            return -_as_bv(operand, ctx.w)
        return z3.Not(_as_bool(operand))

    if isinstance(node, ir.Compare):
        return _eval_compare(node, env, ctx)

    if isinstance(node, ir.BoolOp):
        parts = [_as_bool(_eval(v, env, ctx)) for v in node.values]
        return z3.And(parts) if node.op == "and" else z3.Or(parts)

    if isinstance(node, ir.IfExp):
        cond = _as_bool(_eval(node.test, env, ctx))
        return _merge(cond, _eval(node.body, env, ctx), _eval(node.orelse, env, ctx), ctx.w)

    raise AssertionError(f"unhandled expression node: {node!r}")


def _eval_binop(node: ir.BinOp, env: _Env, ctx: _Ctx) -> z3.ExprRef:
    left = _as_bv(_eval(node.left, env, ctx), ctx.w)
    right = _as_bv(_eval(node.right, env, ctx), ctx.w)
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


def _eval_compare(node: ir.Compare, env: _Env, ctx: _Ctx) -> z3.ExprRef:
    left = _eval(node.left, env, ctx)
    right = _eval(node.right, env, ctx)
    op = node.op
    if op in ("==", "!="):
        if z3.is_bool(left) and z3.is_bool(right):
            return left == right if op == "==" else left != right
        left, right = _as_bv(left, ctx.w), _as_bv(right, ctx.w)
        return left == right if op == "==" else left != right
    left, right = _as_bv(left, ctx.w), _as_bv(right, ctx.w)  # signed BV ordering
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
    needs_adjust = z3.And(r != zero, z3.Xor(r < zero, b < zero))
    return z3.If(needs_adjust, q - one, q)


def _floormod(a: z3.ExprRef, b: z3.ExprRef) -> z3.ExprRef:
    """Modulo matching Python `%` (result takes the sign of the divisor)."""
    return a - _floordiv(a, b) * b


# --- sort coercions / merging ----------------------------------------------

def _as_bool(e: z3.ExprRef) -> z3.ExprRef:
    if z3.is_bool(e):
        return e
    return e != z3.BitVecVal(0, e.size())


def _as_bv(e: z3.ExprRef, w: int) -> z3.ExprRef:
    if z3.is_bv(e):
        return e
    return z3.If(e, z3.BitVecVal(1, w), z3.BitVecVal(0, w))


def _merge(cond: z3.ExprRef, then_val: z3.ExprRef, else_val: z3.ExprRef, w: int) -> z3.ExprRef:
    if z3.is_bool(then_val) and z3.is_bool(else_val):
        return z3.If(cond, then_val, else_val)
    return z3.If(cond, _as_bv(then_val, w), _as_bv(else_val, w))
