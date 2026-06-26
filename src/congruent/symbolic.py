"""Symbolic interpreter — Stage 2 core: IR -> Z3 expressions.

This is path (A) from the foundational doc §3: a from-scratch mini symbolic
interpreter. It lowers a function to a Z3 *summary* over fresh symbolic inputs in
a single state-threading pass that carries `(env, returned, return_value)`. Each
statement executes only where it is "live" (`pc ∧ ¬returned`), so an early
`return` anywhere — including inside a loop — correctly short-circuits the rest.
Bounded `for` loops are unrolled to `--bound` iterations. Falling off the end
without returning is folded into the error condition (Python would return None).

**Semantics must mirror `difftest`'s concrete interpreter exactly**, or the two
stages could disagree:
    - integers are `int_width`-bit bitvectors (arithmetic wraps mod 2**width),
    - `//` and `%` are Python floor division / modulo (not C truncation),
    - signed comparisons.

**Runtime errors are modeled, not assumed away.** A function's summary is a
pair `(output, error)`: `error` is the disjunction of every *guarded* runtime
error — an out-of-bounds `xs[i]` or a division/modulo by zero — where each is
guarded by the path condition under which it actually executes. Two functions
are equivalent iff their error conditions match *and* their outputs agree
whenever neither errors. This catches a rewrite that crashes where the original
didn't, with no unsound "assume in-bounds" caveat.

**Bounded model checking.** A `for range` loop is unrolled `bound` times;
iteration k takes effect under `start + k < stop`. We record an *in-bound
assumption* (the loop runs 0..`bound` times with no index-window wrap), guarded
by the loop's path condition — that is what makes a loop verdict an honest
"EQUIVALENT up to bound N". `list[int]` inputs are length-bounded to `bound`, so
iterating one is always within the unroll bound.

Anything not soundly modeled (unsupported param types, variables first assigned
inside a loop, a variable possibly-undefined after an `if`) raises
`UnsupportedForProof`; the orchestrator then falls back to the differential verdict.
"""

from __future__ import annotations

from dataclasses import dataclass

import z3

from congruent import ir
from congruent.ir import Function

_Env = dict  # name -> (z3.ExprRef | SymList)
_TRUE = z3.BoolVal(True)


class UnsupportedForProof(Exception):
    """The symbolic stage cannot soundly model this function (yet)."""


@dataclass(frozen=True)
class SymList:
    """A symbolic list[int]: a Z3 array of elements plus a symbolic length."""

    arr: z3.ArrayRef
    length: z3.ExprRef  # BitVec; constrained 0 <= length <= bound at the query


@dataclass
class Summary:
    """The symbolic result of one function."""

    output: z3.ExprRef
    error: z3.BoolRef              # condition under which the function raises at runtime
    assumptions: list[z3.BoolRef]  # in-bound conditions accumulated from loops
    unrolled: bool                 # whether any loop was unrolled (verdict is bounded)


class _Ctx:
    __slots__ = ("w", "bound", "assumptions", "unrolled", "error_terms", "ret_kind")

    def __init__(self, width: int, bound: int) -> None:
        self.w = width
        self.bound = bound
        self.assumptions: list[z3.BoolRef] = []
        self.error_terms: list[z3.BoolRef] = []
        self.unrolled = False
        self.ret_kind = "int"  # "int" | "bool" | "list"


def make_inputs(
    params: list[ir.Param], int_width: int, bound: int
) -> tuple[list, list[z3.BoolRef]]:
    """Create fresh shared inputs plus well-formedness constraints.

    Returns (values, constraints). A scalar param yields a Z3 symbol; a
    `list[int]` yields a `SymList` plus a constraint bounding its length to
    `[0, bound]` (the bounded-array domain).
    """
    values: list = []
    constraints: list[z3.BoolRef] = []
    for i, param in enumerate(params):
        if param.type_name == "int":
            values.append(z3.BitVec(f"in{i}", int_width))
        elif param.type_name == "bool":
            values.append(z3.Bool(f"in{i}"))
        elif param.type_name == "list[int]":
            arr = z3.Array(f"in{i}", z3.BitVecSort(int_width), z3.BitVecSort(int_width))
            length = z3.BitVec(f"in{i}_len", int_width)
            values.append(SymList(arr, length))
            zero = z3.BitVecVal(0, int_width)
            constraints.append(z3.And(zero <= length, length <= z3.BitVecVal(bound, int_width)))
        else:
            raise UnsupportedForProof(f"parameter type {param.type_name!r} not modeled yet")
    return values, constraints


def lower_preconditions(
    function: Function, input_symbols: list, int_width: int
) -> list[z3.BoolRef]:
    """Lower a function's `assume(...)` preconditions to Z3 boolean constraints."""
    env: _Env = {p.name: sym for p, sym in zip(function.params, input_symbols)}
    ctx = _Ctx(int_width, 0)  # bound irrelevant; error_terms here are discarded
    return [_as_bool(_eval(pc.expr, env, ctx, _TRUE)) for pc in function.preconditions]


def summarize(
    function: Function, input_symbols: list, int_width: int, bound: int
) -> Summary:
    """Lower `function` to a `Summary` over the (positionally bound) inputs."""
    env: _Env = {p.name: sym for p, sym in zip(function.params, input_symbols)}
    ctx = _Ctx(int_width, bound)
    ctx.ret_kind = _ret_kind(function.return_type)
    retval0 = _empty_retval(ctx.ret_kind, int_width)

    _env, returned, retval = _exec_seq(function.body, env, ctx, _TRUE, z3.BoolVal(False), retval0)

    # Falling off the end without returning is itself a runtime error (Python
    # would return None), so it's folded into the error condition.
    error = z3.Or(ctx.error_terms + [z3.Not(returned)])
    return Summary(retval, error, ctx.assumptions, ctx.unrolled)


# --- statement execution (single state-threading pass) ----------------------
# Threads (env, returned, retval) through a statement sequence. `returned` is the
# condition under which the function has already returned; statements execute
# only where they are "live" = pc ∧ ¬returned, so a `return` anywhere (including
# inside a loop) correctly short-circuits the rest.

def _exec_seq(
    stmts, env: _Env, ctx: _Ctx, pc: z3.BoolRef, returned: z3.BoolRef, retval: z3.ExprRef
):
    cur = dict(env)
    for stmt in stmts:
        live = z3.And(pc, z3.Not(returned))

        if isinstance(stmt, ir.Return):
            val = _coerce_return(_eval(stmt.value, cur, ctx, live), ctx)
            retval = _merge(live, val, retval, ctx.w)
            returned = z3.Or(returned, live)

        elif isinstance(stmt, ir.Assign):
            val = _eval(stmt.value, cur, ctx, live)
            cur[stmt.target] = _merge(live, val, cur[stmt.target], ctx.w) if stmt.target in cur else val

        elif isinstance(stmt, ir.If):
            cond = _as_bool(_eval(stmt.test, cur, ctx, live))
            then_env, returned, retval = _exec_seq(
                stmt.body, cur, ctx, z3.And(live, cond), returned, retval
            )
            else_env, returned, retval = _exec_seq(
                stmt.orelse, cur, ctx, z3.And(live, z3.Not(cond)), returned, retval
            )
            for name in _assigned_names(stmt.body) | _assigned_names(stmt.orelse):
                then_v = then_env.get(name, cur.get(name))
                else_v = else_env.get(name, cur.get(name))
                if then_v is None or else_v is None:
                    raise UnsupportedForProof(f"variable {name!r} may be undefined after an if")
                cur[name] = _merge(cond, then_v, else_v, ctx.w)

        elif isinstance(stmt, ir.For):
            cur, returned, retval = _unroll_for(stmt, cur, ctx, live, returned, retval)

        elif isinstance(stmt, ir.ForEach):
            cur, returned, retval = _unroll_foreach(stmt, cur, ctx, live, returned, retval)

        else:
            raise AssertionError(f"unhandled statement node: {stmt!r}")

    return cur, returned, retval


# --- loop unrolling (threads control state; `return` inside loops is allowed) -

def _unroll_for(loop: ir.For, env: _Env, ctx: _Ctx, pc, returned, retval):
    ctx.unrolled = True
    start = _as_bv(_eval(loop.start, env, ctx, pc), ctx.w)
    stop = _as_bv(_eval(loop.stop, env, ctx, pc), ctx.w)
    written = _require_initialized(loop, env)

    cur = dict(env)
    for k in range(ctx.bound):
        idx = start + z3.BitVecVal(k, ctx.w)
        guard = idx < stop  # signed: iteration k runs iff start + k < stop
        body_env = dict(cur)
        body_env[loop.var] = idx
        after, returned, retval = _exec_seq(loop.body, body_env, ctx, z3.And(pc, guard), returned, retval)
        for name in written:
            cur[name] = _merge(guard, after[name], cur[name], ctx.w)

    # In-bound assumption (guarded by pc): the loop runs 0..bound times and its
    # index window does not wrap, i.e. stop in [start, start + bound] with no
    # overflow. The no-wrap part keeps "up to bound N" honest even when the loop
    # bound expression could overflow in fixed width.
    end = start + z3.BitVecVal(ctx.bound, ctx.w)
    in_bound = z3.And(start <= end, start <= stop, stop <= end)
    ctx.assumptions.append(z3.Implies(pc, in_bound))
    return cur, returned, retval


def _unroll_foreach(loop: ir.ForEach, env: _Env, ctx: _Ctx, pc, returned, retval):
    ctx.unrolled = True
    seq = _eval(loop.iterable, env, ctx, pc)
    if not isinstance(seq, SymList):
        raise UnsupportedForProof("can only iterate a list[int]")
    written = _require_initialized(loop, env)

    # No extra in-bound assumption: list length is bounded to [0, bound] by
    # make_inputs, so `bound` unrollings cover every valid list.
    cur = dict(env)
    for k in range(ctx.bound):
        guard = z3.BitVecVal(k, ctx.w) < seq.length  # iteration k runs iff k < len
        body_env = dict(cur)
        body_env[loop.var] = z3.Select(seq.arr, z3.BitVecVal(k, ctx.w))
        after, returned, retval = _exec_seq(loop.body, body_env, ctx, z3.And(pc, guard), returned, retval)
        for name in written:
            cur[name] = _merge(guard, after[name], cur[name], ctx.w)
    return cur, returned, retval


def _require_initialized(loop, env: _Env) -> set[str]:
    """Variables written in a loop must be initialized before it (so every merge
    has a well-defined 'iteration skipped' value). Returns the written names."""
    written = _assigned_names(loop.body) - {loop.var}
    missing = written - set(env)
    if missing:
        raise UnsupportedForProof(
            f"variable(s) {sorted(missing)} assigned in a loop but not initialized before it"
        )
    return written
    return cur


def _assigned_names(stmts) -> set[str]:
    names: set[str] = set()
    for stmt in stmts:
        if isinstance(stmt, ir.Assign):
            names.add(stmt.target)
        elif isinstance(stmt, ir.If):
            names |= _assigned_names(stmt.body) | _assigned_names(stmt.orelse)
        elif isinstance(stmt, (ir.For, ir.ForEach)):
            names |= _assigned_names(stmt.body) - {stmt.var}
    return names


# --- expression evaluation -------------------------------------------------
# `pc` is the path condition under which `node` is evaluated; runtime-error
# terms are guarded by it so an error in a not-taken branch never fires.

def _eval(node: ir.Expr, env: _Env, ctx: _Ctx, pc: z3.BoolRef) -> z3.ExprRef:
    if isinstance(node, ir.Name):
        if node.id not in env:
            raise UnsupportedForProof(f"reference to unbound name {node.id!r}")
        return env[node.id]

    if isinstance(node, ir.Const):
        if node.type_name == "bool":
            return z3.BoolVal(bool(node.value))
        return z3.BitVecVal(node.value, ctx.w)  # z3 reduces mod 2**w

    if isinstance(node, ir.BinOp):
        return _eval_binop(node, env, ctx, pc)

    if isinstance(node, ir.UnaryOp):
        operand = _eval(node.operand, env, ctx, pc)
        if node.op == "-":
            return -_as_bv(operand, ctx.w)
        return z3.Not(_as_bool(operand))

    if isinstance(node, ir.Compare):
        return _eval_compare(node, env, ctx, pc)

    if isinstance(node, ir.BoolOp):
        # Short-circuit: later operands only execute under the accumulated guard,
        # so a guarded access like `i < len(xs) and xs[i] > 0` is error-free.
        terms = []
        cur_pc = pc
        for value in node.values:
            term = _as_bool(_eval(value, env, ctx, cur_pc))
            terms.append(term)
            cur_pc = z3.And(cur_pc, term if node.op == "and" else z3.Not(term))
        return z3.And(terms) if node.op == "and" else z3.Or(terms)

    if isinstance(node, ir.IfExp):
        cond = _as_bool(_eval(node.test, env, ctx, pc))
        body_val = _eval(node.body, env, ctx, z3.And(pc, cond))
        else_val = _eval(node.orelse, env, ctx, z3.And(pc, z3.Not(cond)))
        return _merge(cond, body_val, else_val, ctx.w)

    if isinstance(node, ir.Len):
        value = _eval(node.value, env, ctx, pc)
        if not isinstance(value, SymList):
            raise UnsupportedForProof("len() of a non-list value")
        return value.length

    if isinstance(node, ir.Subscript):
        seq = _eval(node.value, env, ctx, pc)
        if not isinstance(seq, SymList):
            raise UnsupportedForProof("indexing a non-list value")
        index = _as_bv(_eval(node.index, env, ctx, pc), ctx.w)
        zero = z3.BitVecVal(0, ctx.w)
        in_bounds = z3.And(zero <= index, index < seq.length)  # signed; no negative indexing
        ctx.error_terms.append(z3.And(pc, z3.Not(in_bounds)))
        return z3.Select(seq.arr, index)

    if isinstance(node, ir.ListLit):
        return _build_list([_eval(e, env, ctx, pc) for e in node.elements], ctx.w)

    raise AssertionError(f"unhandled expression node: {node!r}")


def _eval_binop(node: ir.BinOp, env: _Env, ctx: _Ctx, pc: z3.BoolRef) -> z3.ExprRef:
    left = _eval(node.left, env, ctx, pc)
    if isinstance(left, SymList):
        if node.op != "+":
            raise UnsupportedForProof("unsupported list operation")
        # Fast path: `xs + [a, b, ...]` is an append — a couple of Stores at the
        # tail, far cheaper than the general capacity reconstruction.
        if isinstance(node.right, ir.ListLit):
            return _append(left, [_eval(e, env, ctx, pc) for e in node.right.elements], ctx)
        right = _eval(node.right, env, ctx, pc)
        if not isinstance(right, SymList):
            raise UnsupportedForProof("unsupported list operation")
        return _concat(left, right, ctx)

    right = _eval(node.right, env, ctx, pc)
    if isinstance(right, SymList):
        raise UnsupportedForProof("unsupported list operation")
    left = _as_bv(left, ctx.w)
    right = _as_bv(right, ctx.w)
    op = node.op
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if op in ("//", "%"):
        # Division/modulo by zero is a runtime error, guarded by the path condition.
        ctx.error_terms.append(z3.And(pc, right == z3.BitVecVal(0, ctx.w)))
        return _floordiv(left, right) if op == "//" else _floormod(left, right)
    raise AssertionError(f"unhandled binop {op!r}")


def _eval_compare(node: ir.Compare, env: _Env, ctx: _Ctx, pc: z3.BoolRef) -> z3.ExprRef:
    left = _eval(node.left, env, ctx, pc)
    right = _eval(node.right, env, ctx, pc)
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
# These are total (defined even for a zero divisor); the value under a zero
# divisor is unused because the guarded error term rules that input out.

def _floordiv(a: z3.ExprRef, b: z3.ExprRef) -> z3.ExprRef:
    """Floor division matching Python `//`."""
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


def _merge(cond: z3.ExprRef, then_val, else_val, w: int):
    if isinstance(then_val, SymList) or isinstance(else_val, SymList):
        return SymList(
            z3.If(cond, then_val.arr, else_val.arr),
            z3.If(cond, then_val.length, else_val.length),
        )
    if z3.is_bool(then_val) and z3.is_bool(else_val):
        return z3.If(cond, then_val, else_val)
    return z3.If(cond, _as_bv(then_val, w), _as_bv(else_val, w))


# --- list[int] values ------------------------------------------------------

def _empty_list(width: int) -> SymList:
    arr = z3.K(z3.BitVecSort(width), z3.BitVecVal(0, width))  # all-zero array
    return SymList(arr, z3.BitVecVal(0, width))


def _build_list(elements, width: int) -> SymList:
    result = _empty_list(width)
    arr = result.arr
    for i, element in enumerate(elements):
        arr = z3.Store(arr, z3.BitVecVal(i, width), _as_bv(element, width))
    return SymList(arr, z3.BitVecVal(len(elements), width))


def _append(a: SymList, elements, ctx: _Ctx) -> SymList:
    """`a + [e0, e1, ...]` — store each element at the running tail (cheap)."""
    arr, length = a.arr, a.length
    for element in elements:
        arr = z3.Store(arr, length, _as_bv(element, ctx.w))
        length = length + z3.BitVecVal(1, ctx.w)
    return SymList(arr, length)


def _concat(a: SymList, b: SymList, ctx: _Ctx) -> SymList:
    """General list+list concatenation. Builds slots 0..bound-1; results longer
    than `bound` are ruled out of scope by the output-length bound in the query."""
    arr = z3.K(z3.BitVecSort(ctx.w), z3.BitVecVal(0, ctx.w))
    for k in range(ctx.bound):
        kk = z3.BitVecVal(k, ctx.w)
        value = z3.If(z3.ULT(kk, a.length), z3.Select(a.arr, kk), z3.Select(b.arr, kk - a.length))
        arr = z3.Store(arr, kk, value)
    return SymList(arr, a.length + b.length)


# --- return-value kinds ----------------------------------------------------

def _ret_kind(return_type: str) -> str:
    if return_type == "bool":
        return "bool"
    if return_type == "list[int]":
        return "list"
    return "int"


def _empty_retval(ret_kind: str, width: int):
    if ret_kind == "bool":
        return z3.BoolVal(False)
    if ret_kind == "list":
        return _empty_list(width)
    return z3.BitVecVal(0, width)


def _coerce_return(raw, ctx: _Ctx):
    if ctx.ret_kind == "bool":
        return _as_bool(raw)
    if ctx.ret_kind == "list":
        if not isinstance(raw, SymList):
            raise UnsupportedForProof("function annotated -> list[int] did not return a list")
        return raw
    return _as_bv(raw, ctx.w)
