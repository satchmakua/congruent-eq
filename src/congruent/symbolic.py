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
    """A symbolic bounded sequence: a Z3 array of elements plus a symbolic length.

    `kind` is "int" for `list[int]` (indexing/iteration yields an int) or "char"
    for `str` (a character is itself a length-1 string, so indexing/iteration
    yields a 1-char `SymList`). The element array holds code points either way.
    """

    arr: z3.ArrayRef
    length: z3.ExprRef  # BitVec; constrained 0 <= length <= bound at the query
    kind: str = "int"  # "int" | "char"


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
    zero = z3.BitVecVal(0, int_width)
    cap = z3.BitVecVal(bound, int_width)
    for i, param in enumerate(params):
        if param.type_name == "int":
            values.append(z3.BitVec(f"in{i}", int_width))
        elif param.type_name == "bool":
            values.append(z3.Bool(f"in{i}"))
        elif param.type_name in ("list[int]", "str"):
            kind = "char" if param.type_name == "str" else "int"
            arr = z3.Array(f"in{i}", z3.BitVecSort(int_width), z3.BitVecSort(int_width))
            length = z3.BitVec(f"in{i}_len", int_width)
            values.append(SymList(arr, length, kind))
            constraints.append(z3.And(zero <= length, length <= cap))
            if kind == "char":
                # Constrain code points to ASCII so counterexamples decode cleanly.
                ascii_max = z3.BitVecVal(127, int_width)
                for k in range(bound):
                    e = z3.Select(arr, z3.BitVecVal(k, int_width))
                    constraints.append(z3.And(zero <= e, e <= ascii_max))
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

    _env, returned, retval, _b, _c = _exec_seq(
        function.body, env, ctx, _TRUE, z3.BoolVal(False), retval0, z3.BoolVal(False), z3.BoolVal(False)
    )

    # Falling off the end without returning is itself a runtime error (Python
    # would return None), so it's folded into the error condition.
    error = z3.Or(ctx.error_terms + [z3.Not(returned)])
    return Summary(retval, error, ctx.assumptions, ctx.unrolled)


# --- statement execution (single state-threading pass) ----------------------
# Threads (env, returned, retval, broken, continued). A statement executes only
# where it is "live" = pc ∧ ¬returned ∧ ¬broken ∧ ¬continued. `returned` is
# function-level; `broken`/`continued` refer to the nearest enclosing loop, which
# resets `continued` each iteration and consumes `broken` to stop iterating.

def _exec_seq(stmts, env: _Env, ctx: _Ctx, pc, returned, retval, broken, continued):
    cur = dict(env)
    for stmt in stmts:
        live = z3.And(pc, z3.Not(returned), z3.Not(broken), z3.Not(continued))

        if isinstance(stmt, ir.Return):
            val = _coerce_return(_eval(stmt.value, cur, ctx, live), ctx)
            retval = _merge(live, val, retval, ctx.w)
            returned = z3.Or(returned, live)

        elif isinstance(stmt, ir.Break):
            broken = z3.Or(broken, live)

        elif isinstance(stmt, ir.Continue):
            continued = z3.Or(continued, live)

        elif isinstance(stmt, ir.Assign):
            val = _eval(stmt.value, cur, ctx, live)
            cur[stmt.target] = _merge(live, val, cur[stmt.target], ctx.w) if stmt.target in cur else val

        elif isinstance(stmt, ir.If):
            cond = _as_bool(_eval(stmt.test, cur, ctx, live))
            then_env, returned, retval, broken, continued = _exec_seq(
                stmt.body, cur, ctx, z3.And(live, cond), returned, retval, broken, continued
            )
            else_env, returned, retval, broken, continued = _exec_seq(
                stmt.orelse, cur, ctx, z3.And(live, z3.Not(cond)), returned, retval, broken, continued
            )
            for name in _assigned_names(stmt.body) | _assigned_names(stmt.orelse):
                then_v = then_env.get(name, cur.get(name))
                else_v = else_env.get(name, cur.get(name))
                if then_v is None or else_v is None:
                    raise UnsupportedForProof(f"variable {name!r} may be undefined after an if")
                cur[name] = _merge(cond, then_v, else_v, ctx.w)

        elif isinstance(stmt, ir.For):
            # A nested loop manages its own break/continue; the outer ones pass through.
            cur, returned, retval = _unroll_for(stmt, cur, ctx, live, returned, retval)

        elif isinstance(stmt, ir.ForEach):
            cur, returned, retval = _unroll_foreach(stmt, cur, ctx, live, returned, retval)

        else:
            raise AssertionError(f"unhandled statement node: {stmt!r}")

    return cur, returned, retval, broken, continued


# --- loop unrolling -------------------------------------------------------
# Each loop owns its `broken` (accumulates across iterations, stopping the loop)
# and a fresh `continued` per iteration. `return` still propagates out via
# `returned`. The body runs only where guard ∧ ¬returned ∧ ¬broken holds.

def _run_iterations(loop, cur, ctx, pc, returned, retval, idx_of, guard_of):
    written = _require_initialized(loop, cur)
    broken = z3.BoolVal(False)
    cur = dict(cur)
    for k in range(ctx.bound):
        guard = guard_of(k)
        body_env = dict(cur)
        body_env[loop.var] = idx_of(k)
        after, returned, retval, broken, _continued = _exec_seq(
            loop.body, body_env, ctx, z3.And(pc, guard), returned, retval, broken, z3.BoolVal(False)
        )
        for name in written:
            cur[name] = _merge(guard, after[name], cur[name], ctx.w)
    return cur, returned, retval


def _unroll_for(loop: ir.For, env: _Env, ctx: _Ctx, pc, returned, retval):
    ctx.unrolled = True
    start = _as_bv(_eval(loop.start, env, ctx, pc), ctx.w)
    stop = _as_bv(_eval(loop.stop, env, ctx, pc), ctx.w)

    cur, returned, retval = _run_iterations(
        loop, env, ctx, pc, returned, retval,
        idx_of=lambda k: start + z3.BitVecVal(k, ctx.w),
        guard_of=lambda k: (start + z3.BitVecVal(k, ctx.w)) < stop,  # signed: start+k < stop
    )

    # In-bound assumption (guarded by pc): the loop runs 0..bound times and its
    # index window does not wrap, i.e. stop in [start, start + bound] with no
    # overflow. The no-wrap part keeps "up to bound N" honest even when the loop
    # bound expression could overflow in fixed width.
    end = start + z3.BitVecVal(ctx.bound, ctx.w)
    ctx.assumptions.append(z3.Implies(pc, z3.And(start <= end, start <= stop, stop <= end)))
    return cur, returned, retval


def _unroll_foreach(loop: ir.ForEach, env: _Env, ctx: _Ctx, pc, returned, retval):
    ctx.unrolled = True
    seq = _eval(loop.iterable, env, ctx, pc)
    if not isinstance(seq, SymList):
        raise UnsupportedForProof("can only iterate a list[int]")

    # No extra in-bound assumption: list length is bounded to [0, bound] by
    # make_inputs, so `bound` unrollings cover every valid list. Iterating a
    # string yields 1-char strings; iterating a list yields int elements.
    def element(k: int):
        idx = z3.BitVecVal(k, ctx.w)
        return _char_at(seq, idx, ctx.w) if seq.kind == "char" else z3.Select(seq.arr, idx)

    return _run_iterations(
        loop, env, ctx, pc, returned, retval,
        idx_of=element,
        guard_of=lambda k: z3.ULT(z3.BitVecVal(k, ctx.w), seq.length),  # k < len
    )


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
            raise UnsupportedForProof("len() of a non-sequence value")
        return value.length

    if isinstance(node, ir.Subscript):
        seq = _eval(node.value, env, ctx, pc)
        if not isinstance(seq, SymList):
            raise UnsupportedForProof("indexing a non-sequence value")
        index = _as_bv(_eval(node.index, env, ctx, pc), ctx.w)
        zero = z3.BitVecVal(0, ctx.w)
        in_bounds = z3.And(zero <= index, index < seq.length)  # signed; no negative indexing
        ctx.error_terms.append(z3.And(pc, z3.Not(in_bounds)))
        # str[i] is a 1-char string; list[i] is the int element.
        return _char_at(seq, index, ctx.w) if seq.kind == "char" else z3.Select(seq.arr, index)

    if isinstance(node, ir.ListLit):
        return _build_seq([_eval(e, env, ctx, pc) for e in node.elements], ctx.w, "int")

    if isinstance(node, ir.StrLit):
        return _build_seq([z3.BitVecVal(ord(c), ctx.w) for c in node.value], ctx.w, "char")

    raise AssertionError(f"unhandled expression node: {node!r}")


def _eval_binop(node: ir.BinOp, env: _Env, ctx: _Ctx, pc: z3.BoolRef) -> z3.ExprRef:
    left = _eval(node.left, env, ctx, pc)
    if isinstance(left, SymList):
        if node.op != "+":
            raise UnsupportedForProof("unsupported sequence operation")
        # Fast path: appending a literal is a couple of Stores at the tail, far
        # cheaper than the general capacity reconstruction.
        if isinstance(node.right, ir.ListLit):
            return _append(left, [_eval(e, env, ctx, pc) for e in node.right.elements], ctx)
        if isinstance(node.right, ir.StrLit):
            return _append(left, [z3.BitVecVal(ord(c), ctx.w) for c in node.right.value], ctx)
        right = _eval(node.right, env, ctx, pc)
        if not isinstance(right, SymList):
            raise UnsupportedForProof("unsupported sequence operation")
        return _concat(left, right, ctx)

    right = _eval(node.right, env, ctx, pc)
    if isinstance(right, SymList):
        raise UnsupportedForProof("unsupported sequence operation")
    left = _as_bv(left, ctx.w)
    right = _as_bv(right, ctx.w)
    op = node.op
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if op in ("//", "%", "c/", "c%"):
        # Division/modulo by zero is a runtime error, guarded by the path condition.
        ctx.error_terms.append(z3.And(pc, right == z3.BitVecVal(0, ctx.w)))
        if op == "//":
            return _floordiv(left, right)          # Python floor division
        if op == "%":
            return _floormod(left, right)          # Python floor modulo
        if op == "c/":
            return left / right                    # C truncating division (z3 bvsdiv)
        return left - (left / right) * right        # C truncating remainder
    raise AssertionError(f"unhandled binop {op!r}")


def _eval_compare(node: ir.Compare, env: _Env, ctx: _Ctx, pc: z3.BoolRef) -> z3.ExprRef:
    left = _eval(node.left, env, ctx, pc)
    right = _eval(node.right, env, ctx, pc)
    op = node.op
    if isinstance(left, SymList) or isinstance(right, SymList):
        # Sequence comparison (str/list): equality only.
        if not (isinstance(left, SymList) and isinstance(right, SymList) and op in ("==", "!=")):
            raise UnsupportedForProof("only == / != is supported on sequences")
        equal = _seq_eq(left, right, ctx)
        return equal if op == "==" else z3.Not(equal)
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
            then_val.kind if isinstance(then_val, SymList) else else_val.kind,
        )
    if z3.is_bool(then_val) and z3.is_bool(else_val):
        return z3.If(cond, then_val, else_val)
    return z3.If(cond, _as_bv(then_val, w), _as_bv(else_val, w))


# --- sequence values (list[int] and str) -----------------------------------

def _empty_seq(width: int, kind: str) -> SymList:
    arr = z3.K(z3.BitVecSort(width), z3.BitVecVal(0, width))  # all-zero array
    return SymList(arr, z3.BitVecVal(0, width), kind)


def _build_seq(elements, width: int, kind: str) -> SymList:
    arr = z3.K(z3.BitVecSort(width), z3.BitVecVal(0, width))
    for i, element in enumerate(elements):
        arr = z3.Store(arr, z3.BitVecVal(i, width), _as_bv(element, width))
    return SymList(arr, z3.BitVecVal(len(elements), width), kind)


def _char_at(seq: SymList, idx: z3.ExprRef, width: int) -> SymList:
    """A single character of a string: a length-1 `str` value."""
    arr = z3.Store(z3.K(z3.BitVecSort(width), z3.BitVecVal(0, width)), z3.BitVecVal(0, width),
                   z3.Select(seq.arr, idx))
    return SymList(arr, z3.BitVecVal(1, width), "char")


def _seq_eq(a: SymList, b: SymList, ctx: _Ctx) -> z3.BoolRef:
    """Sequence equality: same length and equal elements within the bound."""
    same_elems = z3.And(
        [
            z3.Implies(
                z3.ULT(z3.BitVecVal(k, ctx.w), a.length),
                z3.Select(a.arr, z3.BitVecVal(k, ctx.w)) == z3.Select(b.arr, z3.BitVecVal(k, ctx.w)),
            )
            for k in range(ctx.bound)
        ]
    )
    return z3.And(a.length == b.length, same_elems)


def _append(a: SymList, elements, ctx: _Ctx) -> SymList:
    """`a + [e0, e1, ...]` — store each element at the running tail (cheap)."""
    arr, length = a.arr, a.length
    for element in elements:
        arr = z3.Store(arr, length, _as_bv(element, ctx.w))
        length = length + z3.BitVecVal(1, ctx.w)
    return SymList(arr, length, a.kind)


def _concat(a: SymList, b: SymList, ctx: _Ctx) -> SymList:
    """General sequence concatenation. Builds slots 0..bound-1; results longer
    than `bound` are ruled out of scope by the output-length bound in the query."""
    arr = z3.K(z3.BitVecSort(ctx.w), z3.BitVecVal(0, ctx.w))
    for k in range(ctx.bound):
        kk = z3.BitVecVal(k, ctx.w)
        value = z3.If(z3.ULT(kk, a.length), z3.Select(a.arr, kk), z3.Select(b.arr, kk - a.length))
        arr = z3.Store(arr, kk, value)
    return SymList(arr, a.length + b.length, a.kind)


# --- return-value kinds ----------------------------------------------------

def _ret_kind(return_type: str) -> str:
    if return_type == "bool":
        return "bool"
    if return_type == "list[int]":
        return "list"
    if return_type == "str":
        return "str"
    return "int"


def _empty_retval(ret_kind: str, width: int):
    if ret_kind == "bool":
        return z3.BoolVal(False)
    if ret_kind == "list":
        return _empty_seq(width, "int")
    if ret_kind == "str":
        return _empty_seq(width, "char")
    return z3.BitVecVal(0, width)


def _coerce_return(raw, ctx: _Ctx):
    if ctx.ret_kind == "bool":
        return _as_bool(raw)
    if ctx.ret_kind in ("list", "str"):
        want = "char" if ctx.ret_kind == "str" else "int"
        if not isinstance(raw, SymList) or raw.kind != want:
            raise UnsupportedForProof(f"function annotated -> {ctx.ret_kind} did not return one")
        return raw
    return _as_bv(raw, ctx.w)
