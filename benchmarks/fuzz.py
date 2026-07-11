"""Self-validating fuzzer — the strongest soundness check in the project.

Generate random function pairs across the whole feature surface (straight-line
integer expressions, accumulator loops with break/continue, list reductions —
including iteration over *computed* sequences — list map/filter, and string
functions with non-ASCII input), ask Congruent for a verdict, then
*independently* validate it against the concrete fixed-width interpreter (ground
truth):

  - EQUIVALENT     -> the two must agree on many random inputs
  - COUNTEREXAMPLE -> the reported input must actually make them diverge

A violation is an unsound verdict — a false EQUIVALENT or false COUNTEREXAMPLE —
which must never happen. `run()` returns the violation count; the test suite runs
a small deterministic batch, and `python benchmarks/fuzz.py` runs a big one.

Run it:  python benchmarks/fuzz.py [--trials N] [--seed S]
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from congruent import check, ir  # noqa: E402
from congruent.difftest import _eval_function, _int_min_max, _OutOfBound  # noqa: E402
from congruent.equiv import Status  # noqa: E402

WIDTH = 32
BOUND = 5
IMIN, IMAX = _int_min_max(WIDTH)
_LEAVES = [0, 1, -1, 2, 3, IMAX, IMIN, IMAX - 1]
_STR_CHARS = "abé"  # includes a non-ASCII char so the string domain is exercised


# --- random expression generation ------------------------------------------

def _rnd_int(rng, depth, names):
    if depth <= 0 or rng.random() < 0.4:
        return ir.Name(rng.choice(names)) if rng.random() < 0.6 else ir.Const(rng.choice(_LEAVES), "int")
    roll = rng.random()
    if roll < 0.65:
        op = rng.choice(["+", "-", "*", "//", "%"])
        return ir.BinOp(op, _rnd_int(rng, depth - 1, names), _rnd_int(rng, depth - 1, names))
    if roll < 0.8:
        return ir.UnaryOp("-", _rnd_int(rng, depth - 1, names))
    return ir.IfExp(_rnd_bool(rng, depth - 1, names),
                    _rnd_int(rng, depth - 1, names), _rnd_int(rng, depth - 1, names))


def _rnd_bool(rng, depth, names):
    if depth <= 0 or rng.random() < 0.55:
        op = rng.choice(["<", "<=", ">", ">=", "==", "!="])
        return ir.Compare(op, _rnd_int(rng, depth - 1, names), _rnd_int(rng, depth - 1, names))
    if rng.random() < 0.7:
        op = rng.choice(["and", "or"])
        return ir.BoolOp(op, (_rnd_bool(rng, depth - 1, names), _rnd_bool(rng, depth - 1, names)))
    return ir.UnaryOp("not", _rnd_bool(rng, depth - 1, names))


def _fn(name, params, ret, body):
    return ir.Function(name, [ir.Param(p, t) for p, t in params], ret, body)


# --- family generators (name, param-types) ---------------------------------

def _expr(name, rng):
    p = ["x", "y", "z"]
    return _fn(name, [(n, "int") for n in p], "int", (ir.Return(_rnd_int(rng, rng.randint(1, 4), p)),))


def _loop(name, rng):
    names = ["i", "total", "x", "y"]
    inner = []
    if rng.random() < 0.5:
        cond = ir.Compare(rng.choice(["==", ">"]), ir.Name("i"), ir.Const(rng.choice([0, 1, 2]), "int"))
        inner.append(ir.If(cond, (rng.choice([ir.Break(), ir.Continue()]),), ()))
    inner.append(ir.Assign("total", ir.BinOp(rng.choice(["+", "-", "*"]),
                                             ir.Name("total"), _rnd_int(rng, rng.randint(1, 3), names))))
    body = (ir.Assign("total", ir.Const(0, "int")),
            ir.For("i", ir.Const(0, "int"), ir.Name("n"), tuple(inner)),
            ir.Return(ir.Name("total")))
    return _fn(name, [("n", "int"), ("x", "int"), ("y", "int")], "int", body)


def _list_reduce(name, rng):
    names = ["x", "total", "y"]
    # iterate either the input list or a COMPUTED sequence (exercises in-bound check)
    iterable = ir.Name("xs")
    if rng.random() < 0.4:
        iterable = ir.BinOp("+", ir.Name("xs"), ir.ListLit((_rnd_int(rng, 1, ["y"]),)))
    inner = []
    if rng.random() < 0.4:
        inner.append(ir.If(ir.Compare(rng.choice(["<", ">"]), ir.Name("x"), ir.Const(0, "int")),
                           (rng.choice([ir.Break(), ir.Continue()]),), ()))
    inner.append(ir.Assign("total", ir.BinOp(rng.choice(["+", "-", "*"]), ir.Name("total"),
                                             _rnd_int(rng, rng.randint(1, 2), names))))
    body = (ir.Assign("total", ir.Const(0, "int")),
            ir.ForEach("x", iterable, tuple(inner)),
            ir.Return(ir.Name("total")))
    return _fn(name, [("xs", "list[int]"), ("y", "int")], "int", body)


def _list_map(name, rng):
    build = ir.Assign("r", ir.BinOp("+", ir.Name("r"), ir.ListLit((_rnd_int(rng, rng.randint(1, 2), ["x"]),))))
    if rng.random() < 0.5:
        inner = (ir.If(ir.Compare(rng.choice(["<", ">", "==", ">="]), ir.Name("x"), ir.Const(rng.choice([0, 1]), "int")),
                       (build,), ()),)
    else:
        inner = (build,)
    body = (ir.Assign("r", ir.ListLit(())), ir.ForEach("x", ir.Name("xs"), inner), ir.Return(ir.Name("r")))
    return _fn(name, [("xs", "list[int]")], "list[int]", body)


def _str_count(name, rng):
    lit = ir.StrLit(rng.choice(list(_STR_CHARS)))
    inner = (ir.If(ir.Compare(rng.choice(["==", "!="]), ir.Name("ch"), lit),
                   (ir.Assign("c", ir.BinOp("+", ir.Name("c"), ir.Const(1, "int"))),), ()),)
    body = (ir.Assign("c", ir.Const(0, "int")), ir.ForEach("ch", ir.Name("s"), inner), ir.Return(ir.Name("c")))
    return _fn(name, [("s", "str")], "int", body)


def _str_concat(name, rng):
    parts = [ir.Name("s"), ir.Name("t"), ir.StrLit(rng.choice(["", "a", "é"]))]
    rng.shuffle(parts)
    expr = parts[0]
    for p in parts[1:]:
        expr = ir.BinOp("+", expr, p)
    return _fn(name, [("s", "str"), ("t", "str")], "str", (ir.Return(expr),))


def _rnd_index(rng, seq):
    """A small, often-negative index expression (exercises Python negative indexing)."""
    r = rng.random()
    if r < 0.3:
        return ir.Name("i")
    if r < 0.55:
        return ir.Const(rng.choice([-1, -2, 0, 1, 2, -3]), "int")
    if r < 0.72:
        return ir.UnaryOp("-", ir.Name("i"))
    if r < 0.86:
        return ir.BinOp("-", ir.Len(seq), ir.Const(rng.choice([1, 2]), "int"))  # end-relative
    return ir.BinOp(rng.choice(["+", "-"]), ir.Name("i"), ir.Const(rng.choice([1, -1]), "int"))


def _index(name, rng):
    """Index a list (int result) or a str (str result), including negative indices."""
    if rng.random() < 0.6:
        seq, ret, param = ir.Name("xs"), "int", ("xs", "list[int]")
    else:
        seq, ret, param = ir.Name("s"), "str", ("s", "str")
    return _fn(name, [param, ("i", "int")], ret, (ir.Return(ir.Subscript(seq, _rnd_index(rng, seq))),))


def _seq_truth(name, rng):
    """Branch on sequence truthiness (`if xs:` / `not xs`) — a non-empty seq is truthy."""
    seq, param = (ir.Name("xs"), ("xs", "list[int]")) if rng.random() < 0.6 else (ir.Name("s"), ("s", "str"))
    cond = ir.UnaryOp("not", seq) if rng.random() < 0.4 else seq
    if rng.random() < 0.5:  # nest with a length comparison, the natural equivalent
        cond = ir.BoolOp(rng.choice(["and", "or"]),
                         (cond, ir.Compare(rng.choice(["==", ">"]), ir.Len(seq), ir.Const(rng.choice([0, 1]), "int"))))
    body = (ir.If(cond, (ir.Return(ir.Const(1, "int")),), (ir.Return(ir.Const(0, "int")),)),)
    return _fn(name, [param], "int", body)


FAMILIES = [_expr, _loop, _list_reduce, _list_map, _str_count, _str_concat, _index, _seq_truth]


# --- concrete validation ---------------------------------------------------

def _gen_arg(rng, type_name):
    if type_name == "list[int]":
        return [rng.choice([0, 1, -1, 2, IMAX, IMIN, rng.randint(IMIN, IMAX)]) for _ in range(rng.randint(0, BOUND))]
    if type_name == "str":
        return "".join(rng.choice(_STR_CHARS) for _ in range(rng.randint(0, BOUND)))
    return rng.randint(IMIN, IMAX)


def _outcome(fn, args):
    try:
        return ("val", _eval_function(fn, args, WIDTH, BOUND))
    except _OutOfBound:
        return ("oob", None)
    except Exception:  # noqa: BLE001 — any raise counts as one "error" behavior
        return ("err", None)


def _violation(f, g, verdict, param_types, param_names, rng, sample):
    if verdict.status is Status.EQUIVALENT:
        for _ in range(sample):
            args = [_gen_arg(rng, t) for t in param_types]
            of, og = _outcome(f, args), _outcome(g, args)
            if "oob" in (of[0], og[0]):
                continue  # outside the bounded domain
            if of != og:
                return ("FALSE EQUIVALENT", args, of, og)
    elif verdict.status is Status.COUNTEREXAMPLE:
        args = [verdict.counterexample.inputs[n] for n in param_names]
        of, og = _outcome(f, args), _outcome(g, args)
        if of[0] != "oob" and og[0] != "oob" and of == og:
            return ("FALSE COUNTEREXAMPLE", args, of, og)
    return None


def run(trials: int = 200, seed: int = 0, sample: int = 200, report=lambda _m: None) -> int:
    """Run `trials` random pairs; return the number of unsound verdicts."""
    rng = random.Random(seed)
    violations = 0
    for i in range(trials):
        family = rng.choice(FAMILIES)
        f = family("f", rng)
        g = f if rng.random() < 0.4 else family("g", rng)
        param_types = [p.type_name for p in f.params]
        param_names = [p.name for p in f.params]
        try:
            verdict = check(f, g, bound=BOUND, int_width=WIDTH, trials=120, seed=i)
        except Exception as exc:  # noqa: BLE001
            violations += 1
            report(f"[{i}] CRASH {type(exc).__name__}: {exc}")
            continue
        bad = _violation(f, g, verdict, param_types, param_names, rng, sample)
        if bad:
            violations += 1
            report(f"[{i}] UNSOUND {bad[0]}: args={bad[1]} f={bad[2]} g={bad[3]}")
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    violations = run(args.trials, args.seed, report=print)
    print(f"{args.trials} trials: {violations} unsound verdict(s)")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
