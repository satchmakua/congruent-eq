"""Independent fixed-width oracle — the check for the *wrapping* itself.

`realpy_fuzz.py` validates the interpreter's semantics against real Python, but
it deliberately runs at width 64 with small values so nothing overflows: that
isolates semantics from wrapping, which means the two's-complement wrapping —
the tool's whole reason to exist — was previously validated only by construction
and hand-written unit tests, never by an *independent* oracle.

This closes that gap. numpy's integer scalars wrap on overflow in C, at the
hardware level, with an implementation that shares no code with Congruent's
`difftest._wrap` masking. So it is a genuinely independent reference for the
fixed-width arithmetic. We generate random integer functions, evaluate each two
ways at a *small* width (8/16 — where overflow is the common case, not the
exception) over boundary-biased inputs, and assert the two engines agree:

    Congruent's concrete interpreter   (Python: mask + sign-adjust)
    this file's numpy evaluator        (numpy: C two's-complement scalars)

The only intended divergence is integer division by zero: Python/Congruent
raise, numpy returns 0. The numpy evaluator raises to match, so both sides
classify it as the same "error" behavior. `INT_MIN // -1` (which also overflows)
is *not* special-cased — both engines wrap it to `INT_MIN`, and the exhaustive
primitive check in the tests confirms it.

Run it:  python benchmarks/numpy_oracle.py [--trials N] [--seed S] [--width W]
"""

from __future__ import annotations

import argparse
import random
import sys
import warnings
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import numpy as np  # noqa: E402

from congruent import ir  # noqa: E402
from congruent.difftest import _eval_function, _int_min_max, _OutOfBound  # noqa: E402

# numpy integer overflow is exactly the behavior under test, so silence its
# "overflow encountered" RuntimeWarnings rather than let them fail the run.
np.seterr(over="ignore", divide="ignore", invalid="ignore", under="ignore")
warnings.filterwarnings("ignore", category=RuntimeWarning)

_DTYPES = {8: np.int8, 16: np.int16, 32: np.int32, 64: np.int64}

BOUND = 8


# --- the independent numpy evaluator ---------------------------------------
#
# Deliberately a *separate* interpreter from difftest: every integer operation
# is performed on numpy fixed-width scalars, so the wrapping comes from numpy's
# C arithmetic, not from any masking of ours. Only the int/bool subset is
# supported — wrapping is an integer phenomenon; lists/strings are out of scope
# here (realpy_fuzz already covers those semantically).


class _NpOutOfScope(Exception):
    """A loop would run past `bound` — mirror difftest so we compare in-scope only."""


def _truth(value: object) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return int(value) != 0  # type: ignore[arg-type]


def eval_numpy(fn: ir.Function, args: list[object], width: int) -> object:
    """Evaluate `fn` over `args` using numpy `int{width}` arithmetic throughout.

    Returns a Python `int`/`bool`, or raises: `ZeroDivisionError` on `//`/`%` by
    zero (matching Python), or `_NpOutOfScope` if a loop exceeds `bound`.
    """
    dt = _DTYPES[width]
    env: dict[str, object] = {}
    for p, v in zip(fn.params, args):
        env[p.name] = dt(v) if p.type_name == "int" else v

    try:
        _exec_block(fn.body, env, dt, width)
    except _Return as r:
        return _to_python(r.value)
    return None  # fell off the end — Python's None (a value)


class _Return(Exception):
    def __init__(self, value: object) -> None:
        self.value = value


class _Break(Exception):
    pass


class _Continue(Exception):
    pass


def _to_python(value: object) -> object:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    return value


def _exec_block(stmts, env, dt, width) -> None:
    for stmt in stmts:
        _exec_stmt(stmt, env, dt, width)


def _exec_stmt(stmt, env, dt, width) -> None:
    if isinstance(stmt, ir.Return):
        raise _Return(_eval(stmt.value, env, dt, width))
    if isinstance(stmt, ir.Assign):
        env[stmt.target] = _eval(stmt.value, env, dt, width)
        return
    if isinstance(stmt, ir.If):
        branch = stmt.body if _truth(_eval(stmt.test, env, dt, width)) else stmt.orelse
        _exec_block(branch, env, dt, width)
        return
    if isinstance(stmt, ir.Break):
        raise _Break
    if isinstance(stmt, ir.Continue):
        raise _Continue
    if isinstance(stmt, ir.For):
        start = _eval_bound(stmt.start, env)
        stop = _eval_bound(stmt.stop, env)
        imin, imax = _int_min_max(width)
        trip = stop - start
        # Same in-scope rule as difftest, so the two evaluators compare like for like.
        if trip > BOUND or (trip > 0 and not (imin <= start and stop - 1 <= imax)):
            raise _NpOutOfScope
        for i in range(start, stop):
            env[stmt.var] = dt(i)
            try:
                _exec_block(stmt.body, env, dt, width)
            except _Continue:
                continue
            except _Break:
                break
        return
    raise AssertionError(f"unhandled statement: {stmt!r}")


def _eval_bound(node, env) -> int:
    """A loop bound as a plain Python int (control flow, not arithmetic under test)."""
    v = env.get(node.id) if isinstance(node, ir.Name) else None
    if v is not None:
        return int(v)  # type: ignore[arg-type]
    if isinstance(node, ir.Const):
        return int(node.value)  # type: ignore[arg-type]
    raise AssertionError(f"unsupported loop bound: {node!r}")


def _eval(node, env, dt, width):
    if isinstance(node, ir.Name):
        return env[node.id]
    if isinstance(node, ir.Const):
        return dt(node.value) if node.type_name == "int" else node.value
    if isinstance(node, ir.BinOp):
        left = _eval(node.left, env, dt, width)
        right = _eval(node.right, env, dt, width)
        return _binop(node.op, left, right)
    if isinstance(node, ir.UnaryOp):
        operand = _eval(node.operand, env, dt, width)
        return not _truth(operand) if node.op == "not" else dt(0) - _cast(operand, dt)
    if isinstance(node, ir.Compare):
        return _cmp(node.op, _eval(node.left, env, dt, width), _eval(node.right, env, dt, width))
    if isinstance(node, ir.BoolOp):
        # Python and/or return an operand value (short-circuit), not a bool.
        result: object = None
        for v in node.values:
            result = _eval(v, env, dt, width)
            if node.op == "or" and _truth(result):
                return result
            if node.op == "and" and not _truth(result):
                return result
        return result
    if isinstance(node, ir.IfExp):
        chosen = node.body if _truth(_eval(node.test, env, dt, width)) else node.orelse
        return _eval(chosen, env, dt, width)
    raise AssertionError(f"unhandled expression: {node!r}")


def _cast(value, dt):
    return dt(value) if not isinstance(value, np.integer) else value


def _binop(op: str, left, right):
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if op in ("//", "%"):
        if int(right) == 0:
            raise ZeroDivisionError  # numpy would return 0 here; match Python/Congruent
        return left // right if op == "//" else left % right
    raise AssertionError(f"unhandled binop {op!r}")


def _cmp(op: str, a, b) -> bool:
    x, y = int(a), int(b)
    return {"<": x < y, "<=": x <= y, ">": x > y, ">=": x >= y, "==": x == y, "!=": x != y}[op]


# --- outcomes ---------------------------------------------------------------

def _classify(r) -> tuple:
    if r is None:
        return ("none",)
    if isinstance(r, bool):
        return ("bool", r)
    if isinstance(r, int):
        return ("int", r)
    return ("other", repr(r))  # pragma: no cover


def _numpy_outcome(fn, args, width) -> tuple:
    try:
        return _classify(eval_numpy(fn, list(args), width))
    except _NpOutOfScope:
        return ("oob",)
    except Exception:  # noqa: BLE001 — any raise is one "error" behavior
        return ("err",)


def _diff_outcome(fn, args, width) -> tuple:
    try:
        return _classify(_eval_function(fn, list(args), width, BOUND))
    except _OutOfBound:
        return ("oob",)
    except Exception:  # noqa: BLE001
        return ("err",)


# --- generators (integer subset; biased toward overflow) --------------------

def _fn(name, params, body):
    return ir.Function(name, [ir.Param(p, "int") for p in params], "int", tuple(body))


def _rnd_int(rng, depth, names):
    if depth <= 0 or rng.random() < 0.4:
        if rng.random() < 0.6:
            return ir.Name(rng.choice(names))
        return ir.Const(rng.choice([0, 1, -1, 2, 3, -2, 7, -8]), "int")
    roll = rng.random()
    if roll < 0.7:
        return ir.BinOp(rng.choice(["+", "-", "*", "//", "%"]),
                        _rnd_int(rng, depth - 1, names), _rnd_int(rng, depth - 1, names))
    if roll < 0.85:
        return ir.UnaryOp("-", _rnd_int(rng, depth - 1, names))
    return ir.IfExp(
        ir.Compare(rng.choice(["<", ">", "==", ">=", "!="]),
                   _rnd_int(rng, depth - 1, names), _rnd_int(rng, depth - 1, names)),
        _rnd_int(rng, depth - 1, names), _rnd_int(rng, depth - 1, names))


def _expr_family(rng):
    """A pure arithmetic expression over x, y, z — maximal +/-/* overflow."""
    names = ["x", "y", "z"]
    fn = _fn("f", names, [ir.Return(_rnd_int(rng, rng.randint(2, 4), names))])
    return fn, ["x", "y", "z"], None


def _accum_family(rng):
    """`total = 0; for i in range(0, n): total = total OP <expr>; return total` —
    compounds arithmetic across iterations, so multiplies overflow fast."""
    names = ["i", "total", "x"]
    step = ir.Assign("total", ir.BinOp(rng.choice(["+", "-", "*"]),
                                       ir.Name("total"), _rnd_int(rng, 2, names)))
    inner = [step]
    if rng.random() < 0.35:
        inner.insert(0, ir.If(
            ir.Compare(rng.choice(["==", ">"]), ir.Name("i"), ir.Const(rng.choice([0, 1, 2]), "int")),
            (rng.choice([ir.Break(), ir.Continue()]),), ()))
    body = [
        ir.Assign("total", ir.Const(0, "int")),
        ir.For("i", ir.Const(0, "int"), ir.Name("n"), tuple(inner)),
        ir.Return(ir.Name("total")),
    ]
    return _fn("f", ["n", "x"], body), ["x"], "n"  # x boundary-biased; n is the loop count


FAMILIES = [_expr_family, _expr_family, _accum_family]  # weight expressions higher


def _boundary_int(rng, width):
    imin, imax = _int_min_max(width)
    return rng.choice([0, 1, -1, 2, -2, imax, imin, imax - 1, imin + 1,
                       rng.randint(imin, imax), rng.randint(imin, imax)])


def _gen_args(rng, boundary_params, count_param, params, width):
    args = []
    for p in params:
        if p.name == count_param:
            args.append(rng.randint(0, BOUND))       # loop count: in scope by construction
        else:
            args.append(_boundary_int(rng, width))   # everything else: hammer the boundaries
    return args


def run(trials: int = 4000, seed: int = 0, width: int = 8, inputs: int = 8,
        report=lambda _m: None) -> int:
    """Generate `trials` integer functions; return the count of numpy-vs-Congruent
    mismatches at `width`. Division-by-zero and out-of-scope loops are matched/skipped."""
    rng = random.Random(seed)
    mismatches = 0
    for _ in range(trials):
        fn, boundary_params, count_param = rng.choice(FAMILIES)(rng)
        for _ in range(inputs):
            args = _gen_args(rng, boundary_params, count_param, fn.params, width)
            diff = _diff_outcome(fn, args, width)
            npy = _numpy_outcome(fn, args, width)
            if diff[0] == "oob" or npy[0] == "oob":
                continue
            if diff == npy or (diff[0] == "err" and npy[0] == "err"):
                continue
            mismatches += 1
            report(f"MISMATCH width={width} args={args} congruent={diff} numpy={npy}\n"
                   f"  imin,imax={_int_min_max(width)}\n  {fn}")
    return mismatches


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=4000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--width", type=int, default=0,
                        help="fixed-width to test (default: sweep 8, 16, 32, 64)")
    args = parser.parse_args(argv)

    widths = [args.width] if args.width else [8, 16, 32, 64]
    total = 0
    for w in widths:
        m = run(args.trials, args.seed, width=w, report=print)
        print(f"width {w:>2}: {args.trials} functions, {m} numpy-vs-Congruent mismatch(es)")
        total += m
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
