"""Differential testing — Stage 1, the cheap prefilter.

Evaluate both functions on the same concrete inputs and compare. Boundary
inputs first (0, +/-1, INT_MIN/MAX for the width), then random sampling. A
disagreement is returned as a `Counterexample`; this stage never claims
equivalence (only the symbolic stage can — M1).

Crucially, evaluation uses a **fixed-width integer model**: every integer
result is wrapped to `int_width` two's-complement. That is what lets difftest
catch overflow bugs (e.g. the midpoint `(lo + hi) // 2` case) that would be
invisible under Python's unbounded ints. The concrete interpreter here walks
the same IR the symbolic interpreter will, so the two stages share semantics.
"""

from __future__ import annotations

import itertools
import random

from congruent import ir
from congruent.equiv import Counterexample
from congruent.ir import Function


# --- fixed-width integer model --------------------------------------------

def _wrap(value: int, width: int) -> int:
    """Reduce `value` to a signed `width`-bit two's-complement integer."""
    mask = (1 << width) - 1
    value &= mask
    if value >> (width - 1):
        value -= 1 << width
    return value


def _int_min_max(width: int) -> tuple[int, int]:
    return -(1 << (width - 1)), (1 << (width - 1)) - 1


# --- concrete interpreter over the IR -------------------------------------

class _Return(Exception):
    def __init__(self, value: object) -> None:
        self.value = value


class _OutOfBound(Exception):
    """A loop would run more than `bound` iterations — outside the verdict's scope."""


class _Ctx:
    __slots__ = ("width", "bound")

    def __init__(self, width: int, bound: int) -> None:
        self.width = width
        self.bound = bound


def _truth(value: object) -> bool:
    return value != 0 if isinstance(value, int) and not isinstance(value, bool) else bool(value)


def _eval_function(fn: Function, args: list[object], width: int, bound: int) -> object:
    env: dict[str, object] = {}
    for param, value in zip(fn.params, args):
        env[param.name] = _wrap(value, width) if param.type_name == "int" else value
    ctx = _Ctx(width, bound)
    try:
        _exec_block(fn.body, env, ctx)
    except _Return as r:
        return r.value
    raise ValueError(f"{fn.name}: control reached end of function without returning")


def _exec_block(stmts: tuple[ir.Stmt, ...], env: dict[str, object], ctx: _Ctx) -> None:
    for stmt in stmts:
        _exec_stmt(stmt, env, ctx)


def _exec_stmt(stmt: ir.Stmt, env: dict[str, object], ctx: _Ctx) -> None:
    if isinstance(stmt, ir.Return):
        raise _Return(_eval(stmt.value, env, ctx))
    if isinstance(stmt, ir.Assign):
        env[stmt.target] = _eval(stmt.value, env, ctx)
        return
    if isinstance(stmt, ir.If):
        branch = stmt.body if _truth(_eval(stmt.test, env, ctx)) else stmt.orelse
        _exec_block(branch, env, ctx)
        return
    if isinstance(stmt, ir.For):
        start = int(_eval(stmt.start, env, ctx))  # type: ignore[arg-type]
        stop = int(_eval(stmt.stop, env, ctx))  # type: ignore[arg-type]
        if stop - start > ctx.bound:
            raise _OutOfBound
        for i in range(start, stop):
            env[stmt.var] = _wrap(i, ctx.width)
            _exec_block(stmt.body, env, ctx)
        env.pop(stmt.var, None)  # loop variable does not escape the loop
        return
    raise AssertionError(f"unhandled statement node: {stmt!r}")


def _eval(node: ir.Expr, env: dict[str, object], ctx: _Ctx) -> object:
    if isinstance(node, ir.Name):
        if node.id not in env:
            raise NameError(node.id)
        return env[node.id]

    if isinstance(node, ir.Const):
        return _wrap(node.value, ctx.width) if node.type_name == "int" else node.value

    if isinstance(node, ir.BinOp):
        left = _eval(node.left, env, ctx)
        right = _eval(node.right, env, ctx)
        return _wrap(_apply_binop(node.op, int(left), int(right)), ctx.width)

    if isinstance(node, ir.UnaryOp):
        operand = _eval(node.operand, env, ctx)
        if node.op == "-":
            return _wrap(-int(operand), ctx.width)
        return not _truth(operand)

    if isinstance(node, ir.Compare):
        return _apply_cmp(node.op, _eval(node.left, env, ctx), _eval(node.right, env, ctx))

    if isinstance(node, ir.BoolOp):
        if node.op == "and":
            return all(_truth(_eval(v, env, ctx)) for v in node.values)
        return any(_truth(_eval(v, env, ctx)) for v in node.values)

    if isinstance(node, ir.IfExp):
        chosen = node.body if _truth(_eval(node.test, env, ctx)) else node.orelse
        return _eval(chosen, env, ctx)

    raise AssertionError(f"unhandled expression node: {node!r}")


def _apply_binop(op: str, a: int, b: int) -> int:
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "//":
        return a // b
    if op == "%":
        return a % b
    raise AssertionError(f"unhandled binop {op!r}")


def _apply_cmp(op: str, a: object, b: object) -> bool:
    if op == "<":
        return a < b  # type: ignore[operator]
    if op == "<=":
        return a <= b  # type: ignore[operator]
    if op == ">":
        return a > b  # type: ignore[operator]
    if op == ">=":
        return a >= b  # type: ignore[operator]
    if op == "==":
        return a == b
    if op == "!=":
        return a != b
    raise AssertionError(f"unhandled comparison {op!r}")


# --- input generation ------------------------------------------------------

def _boundary_values(type_name: str, width: int) -> list[object]:
    imin, imax = _int_min_max(width)
    if type_name == "int":
        return [0, 1, -1, 2, -2, imax, imin, imax - 1, imin + 1]
    if type_name == "bool":
        return [True, False]
    if type_name == "list[int]":
        return [[], [0], [1], [-1], [imin], [imax], [imax, imin, 0]]
    raise AssertionError(f"no generator for type {type_name!r}")


def _random_value(type_name: str, width: int, bound: int, rng: random.Random) -> object:
    imin, imax = _int_min_max(width)
    if type_name == "int":
        return rng.randint(imin, imax)
    if type_name == "bool":
        return rng.random() < 0.5
    if type_name == "list[int]":
        return [rng.randint(imin, imax) for _ in range(rng.randint(0, bound))]
    raise AssertionError(f"no generator for type {type_name!r}")


def _boundary_inputs(types: list[str], width: int, cap: int) -> list[list[object]]:
    per_param = [_boundary_values(t, width) for t in types]
    out: list[list[object]] = []
    for combo in itertools.product(*per_param):
        out.append(list(combo))
        if len(out) >= cap:
            break
    return out


# --- the stage entry point -------------------------------------------------

def find_counterexample(
    original: Function,
    candidate: Function,
    *,
    bound: int = 8,
    int_width: int = 32,
    trials: int = 2000,
    seed: int = 0,
    boundary_cap: int = 4096,
) -> Counterexample | None:
    """Search for a concrete input on which `original` and `candidate` differ.

    Inputs are generated positionally from `original`'s typed signature
    (callers ensure the two signatures' types match). Returns a `Counterexample`
    on the first disagreement, else `None`. `None` means "no disagreement found
    by sampling" — NOT a proof of equivalence.
    """
    types = [p.type_name for p in original.params]
    rng = random.Random(seed)

    inputs = _boundary_inputs(types, int_width, boundary_cap)
    inputs.extend(
        [_random_value(t, int_width, bound, rng) for t in types] for _ in range(trials)
    )

    for values in inputs:
        cx = _compare(original, candidate, values, int_width, bound)
        if cx is not None:
            return cx
    return None


# outcome kinds
_VALUE = "value"
_ERROR = "error"
_OOB = "oob"  # a loop exceeded the bound on this input — out of scope, skip it


def _outcome(fn: Function, values: list[object], width: int, bound: int) -> tuple[str, object]:
    try:
        return _VALUE, _eval_function(fn, [_copy(v) for v in values], width, bound)
    except _OutOfBound:
        return _OOB, None
    except Exception as exc:  # noqa: BLE001 — any divergence in behavior counts
        return _ERROR, type(exc).__name__


def _copy(value: object) -> object:
    return list(value) if isinstance(value, list) else value


def _compare(
    original: Function, candidate: Function, values: list[object], width: int, bound: int
) -> Counterexample | None:
    kind_o, out_o = _outcome(original, values, width, bound)
    kind_c, out_c = _outcome(candidate, values, width, bound)

    if kind_o == _OOB or kind_c == _OOB:
        return None  # at least one function runs past the bound here — not in scope
    if kind_o == _VALUE and kind_c == _VALUE and out_o == out_c:
        return None
    if kind_o == _ERROR and kind_c == _ERROR and out_o == out_c:
        return None  # both raise the same exception — equivalent on this input

    inputs = {p.name: _copy(v) for p, v in zip(original.params, values)}
    return Counterexample(
        inputs=inputs,
        original_output=out_o if kind_o == _VALUE else f"<raises {out_o}>",
        candidate_output=out_c if kind_c == _VALUE else f"<raises {out_c}>",
    )
