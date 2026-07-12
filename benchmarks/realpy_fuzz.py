"""Real-Python differential oracle — the check no difftest-based test can be.

The fuzzer, the adversarial audits, and the regression suite all validate the
symbolic stage against the concrete interpreter (`difftest`). That is blind to a
bug the two stages *share*: if both diverge from real Python the same way, every
internal cross-check still agrees. (Exactly this hid the negative-indexing bug —
both stages modeled `xs[-1]` as out-of-range, so `return xs[-1]` was "proven"
equivalent to a function that always crashes.)

This uses an INDEPENDENT oracle: unparse each generated IR function back to real
Python source, `exec` it, and compare its behavior to the concrete interpreter.
Values are kept small at width 64 so nothing overflows — that isolates *semantic*
faithfulness from the deliberate fixed-width wrapping. The only tolerated
divergence is falling off the end (real Python returns `None`; Congruent models it
as an error, by design — see README).

Run it:  python benchmarks/realpy_fuzz.py [--trials N] [--seed S]
"""

from __future__ import annotations

import argparse
import random
import sys
from copy import deepcopy
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from congruent import ir  # noqa: E402
from congruent.difftest import _eval_function, _OutOfBound  # noqa: E402

WIDTH = 64  # wide enough that small generated values never overflow
BOUND = 5
SMALL = [0, 1, -1, 2, 3, -2]
STR_CHARS = "abé"


# --- IR -> real Python source ----------------------------------------------

def _expr_src(n) -> str:
    if isinstance(n, ir.Name):
        return n.id
    if isinstance(n, ir.Const):
        if n.type_name == "bool":
            return "True" if n.value else "False"
        return repr(n.value)
    if isinstance(n, ir.StrLit):
        return repr(n.value)
    if isinstance(n, ir.ListLit):
        return "[" + ", ".join(_expr_src(e) for e in n.elements) + "]"
    if isinstance(n, ir.BinOp):
        return f"({_expr_src(n.left)} {n.op} {_expr_src(n.right)})"
    if isinstance(n, ir.UnaryOp):
        return f"(-{_expr_src(n.operand)})" if n.op == "-" else f"(not {_expr_src(n.operand)})"
    if isinstance(n, ir.Compare):
        return f"({_expr_src(n.left)} {n.op} {_expr_src(n.right)})"
    if isinstance(n, ir.BoolOp):
        return "(" + f" {n.op} ".join(_expr_src(v) for v in n.values) + ")"
    if isinstance(n, ir.IfExp):
        return f"({_expr_src(n.body)} if {_expr_src(n.test)} else {_expr_src(n.orelse)})"
    if isinstance(n, ir.Len):
        return f"len({_expr_src(n.value)})"
    if isinstance(n, ir.Subscript):
        return f"{_expr_src(n.value)}[{_expr_src(n.index)}]"
    raise AssertionError(f"cannot unparse expression {n!r}")


def _stmt_src(stmt, indent: int) -> list[str]:
    pad = "    " * indent
    if isinstance(stmt, ir.Return):
        return [f"{pad}return {_expr_src(stmt.value)}"]
    if isinstance(stmt, ir.Assign):
        return [f"{pad}{stmt.target} = {_expr_src(stmt.value)}"]
    if isinstance(stmt, ir.Break):
        return [f"{pad}break"]
    if isinstance(stmt, ir.Continue):
        return [f"{pad}continue"]
    if isinstance(stmt, ir.For):
        return [f"{pad}for {stmt.var} in range({_expr_src(stmt.start)}, {_expr_src(stmt.stop)}):",
                *_block_src(stmt.body, indent + 1)]
    if isinstance(stmt, ir.ForEach):
        return [f"{pad}for {stmt.var} in {_expr_src(stmt.iterable)}:", *_block_src(stmt.body, indent + 1)]
    if isinstance(stmt, ir.If):
        out = [f"{pad}if {_expr_src(stmt.test)}:", *_block_src(stmt.body, indent + 1)]
        if stmt.orelse:
            out += [f"{pad}else:", *_block_src(stmt.orelse, indent + 1)]
        return out
    raise AssertionError(f"cannot unparse statement {stmt!r}")


def _block_src(stmts, indent: int) -> list[str]:
    if not stmts:
        return ["    " * indent + "pass"]
    out: list[str] = []
    for s in stmts:
        out += _stmt_src(s, indent)
    return out


def to_source(fn: ir.Function) -> str:
    header = f"def {fn.name}({', '.join(p.name for p in fn.params)}):"
    return "\n".join([header, *_block_src(fn.body, 1)])


# --- outcomes ---------------------------------------------------------------

def _classify(r) -> tuple:
    if r is None:
        return ("none",)
    if isinstance(r, bool):
        return ("bool", r)
    if isinstance(r, int):
        return ("int", r)
    if isinstance(r, str):
        return ("str", r)
    if isinstance(r, list):
        return ("list", list(r))
    return ("other", repr(r))  # pragma: no cover


def _real_outcome(src: str, name: str, args: list) -> tuple:
    ns: dict = {}
    exec(src, ns)  # noqa: S102 — source is generated from our own IR, not user input
    try:
        return _classify(ns[name](*deepcopy(args)))
    except Exception:  # noqa: BLE001 — any raise is one "error" behavior
        return ("err",)


def _diff_outcome(fn: ir.Function, args: list) -> tuple:
    try:
        return _classify(_eval_function(fn, deepcopy(args), WIDTH, BOUND))
    except _OutOfBound:
        return ("oob",)
    except Exception:  # noqa: BLE001
        return ("err",)


# --- generators (small values; includes indexing families) ------------------

def _rnd_int(rng, depth, names):
    if depth <= 0 or rng.random() < 0.45:
        return ir.Name(rng.choice(names)) if rng.random() < 0.6 else ir.Const(rng.choice(SMALL), "int")
    roll = rng.random()
    if roll < 0.6:
        return ir.BinOp(rng.choice(["+", "-", "*", "//", "%"]),
                        _rnd_int(rng, depth - 1, names), _rnd_int(rng, depth - 1, names))
    if roll < 0.72:
        return ir.UnaryOp("-", _rnd_int(rng, depth - 1, names))
    if roll < 0.86:
        return ir.IfExp(_rnd_bool(rng, depth - 1, names), _rnd_int(rng, depth - 1, names), _rnd_int(rng, depth - 1, names))
    # `and`/`or` in value position return an operand value (int), not a bool
    return ir.BoolOp(rng.choice(["and", "or"]), (_rnd_int(rng, depth - 1, names), _rnd_int(rng, depth - 1, names)))


def _rnd_bool(rng, depth, names):
    if depth <= 0 or rng.random() < 0.6:
        return ir.Compare(rng.choice(["<", "<=", ">", ">=", "==", "!="]),
                          _rnd_int(rng, depth - 1, names), _rnd_int(rng, depth - 1, names))
    return ir.BoolOp(rng.choice(["and", "or"]), (_rnd_bool(rng, depth - 1, names), _rnd_bool(rng, depth - 1, names)))


def _fn(name, params, ret, body):
    return ir.Function(name, [ir.Param(p, t) for p, t in params], ret, tuple(body))


def _rnd_index(rng, seq):
    """A small, often-negative index expression (exercises Python negative indexing)."""
    r = rng.random()
    if r < 0.3:
        return ir.Name("i")
    if r < 0.55:
        return ir.Const(rng.choice([-1, -2, 0, 1, 2, -3, 4]), "int")
    if r < 0.72:
        return ir.UnaryOp("-", ir.Name("i"))
    if r < 0.86:
        return ir.BinOp("-", ir.Len(seq), ir.Const(rng.choice([1, 2]), "int"))  # end-relative
    return ir.BinOp(rng.choice(["+", "-"]), ir.Name("i"), ir.Const(rng.choice([1, -1]), "int"))


def _index_list(name, rng):
    return _fn(name, [("xs", "list[int]"), ("i", "int")], "int",
              [ir.Return(ir.Subscript(ir.Name("xs"), _rnd_index(rng, ir.Name("xs"))))])


def _index_str(name, rng):
    return _fn(name, [("s", "str"), ("i", "int")], "str",
              [ir.Return(ir.Subscript(ir.Name("s"), _rnd_index(rng, ir.Name("s"))))])


def _index_loop(name, rng):
    body = [
        ir.Assign("total", ir.Const(0, "int")),
        ir.For("i", ir.Const(0, "int"), ir.Len(ir.Name("xs")),
               [ir.Assign("total", ir.BinOp("+", ir.Name("total"),
                                            ir.Subscript(ir.Name("xs"), _rnd_index(rng, ir.Name("xs")))))]),
        ir.Return(ir.Name("total")),
    ]
    return _fn(name, [("xs", "list[int]"), ("i", "int")], "int", body)


def _expr(name, rng):
    p = ["x", "y", "z"]
    return _fn(name, [(n, "int") for n in p], "int", [ir.Return(_rnd_int(rng, rng.randint(1, 4), p))])


def _loop(name, rng):
    names = ["i", "total", "x"]
    inner = []
    if rng.random() < 0.5:
        inner.append(ir.If(ir.Compare(rng.choice(["==", ">"]), ir.Name("i"), ir.Const(rng.choice([0, 1, 2]), "int")),
                           (rng.choice([ir.Break(), ir.Continue()]),), ()))
    inner.append(ir.Assign("total", ir.BinOp(rng.choice(["+", "-", "*"]), ir.Name("total"), _rnd_int(rng, 2, names))))
    body = [ir.Assign("total", ir.Const(0, "int")),
            ir.For("i", ir.Const(0, "int"), ir.Name("n"), tuple(inner)), ir.Return(ir.Name("total"))]
    return _fn(name, [("n", "int"), ("x", "int")], "int", body)


def _reduce(name, rng):
    inner = [ir.Assign("total", ir.BinOp(rng.choice(["+", "-", "*"]), ir.Name("total"), _rnd_int(rng, 2, ["x", "total"])))]
    body = [ir.Assign("total", ir.Const(0, "int")), ir.ForEach("x", ir.Name("xs"), tuple(inner)), ir.Return(ir.Name("total"))]
    return _fn(name, [("xs", "list[int]")], "int", body)


def _reduce_computed(name, rng):
    iterable = ir.BinOp("+", ir.Name("xs"), ir.ListLit((_rnd_int(rng, 1, ["y"]),)))
    inner = [ir.Assign("total", ir.BinOp(rng.choice(["+", "-", "*"]), ir.Name("total"), _rnd_int(rng, 2, ["x", "total", "y"])))]
    body = [ir.Assign("total", ir.Const(0, "int")), ir.ForEach("x", iterable, tuple(inner)), ir.Return(ir.Name("total"))]
    return _fn(name, [("xs", "list[int]"), ("y", "int")], "int", body)


def _str_concat(name, rng):
    parts = [ir.Name("s"), ir.Name("t"), ir.StrLit(rng.choice(["", "a", "é", "ab"]))]
    rng.shuffle(parts)
    expr = parts[0]
    for p in parts[1:]:
        expr = ir.BinOp("+", expr, p)
    return _fn(name, [("s", "str"), ("t", "str")], "str", [ir.Return(expr)])


def _str_count(name, rng):
    lit = ir.StrLit(rng.choice(list(STR_CHARS)))
    inner = (ir.If(ir.Compare(rng.choice(["==", "!="]), ir.Name("ch"), lit),
                   (ir.Assign("c", ir.BinOp("+", ir.Name("c"), ir.Const(1, "int"))),), ()),)
    body = [ir.Assign("c", ir.Const(0, "int")), ir.ForEach("ch", ir.Name("s"), inner), ir.Return(ir.Name("c"))]
    return _fn(name, [("s", "str")], "int", body)


def _list_map(name, rng):
    build = ir.Assign("r", ir.BinOp("+", ir.Name("r"), ir.ListLit((_rnd_int(rng, rng.randint(1, 2), ["x"]),))))
    if rng.random() < 0.5:
        inner = (ir.If(ir.Compare(rng.choice(["<", ">", "==", ">="]), ir.Name("x"), ir.Const(rng.choice([0, 1]), "int")),
                       (build,), ()),)
    else:
        inner = (build,)
    body = [ir.Assign("r", ir.ListLit(())), ir.ForEach("x", ir.Name("xs"), inner), ir.Return(ir.Name("r"))]
    return _fn(name, [("xs", "list[int]")], "list[int]", body)


def _seq_truth(name, rng):
    seq, param = (ir.Name("xs"), ("xs", "list[int]")) if rng.random() < 0.6 else (ir.Name("s"), ("s", "str"))
    cond = ir.UnaryOp("not", seq) if rng.random() < 0.4 else seq
    if rng.random() < 0.5:
        cond = ir.BoolOp(rng.choice(["and", "or"]),
                         (cond, ir.Compare(rng.choice(["==", ">"]), ir.Len(seq), ir.Const(rng.choice([0, 1]), "int"))))
    body = [ir.If(cond, (ir.Return(ir.Const(1, "int")),), (ir.Return(ir.Const(0, "int")),))]
    return _fn(name, [param], "int", body)


def _falloff(name, rng):
    # sometimes returns, sometimes falls off the end -> Python None (a value)
    cond = ir.Compare(rng.choice([">", "<", "==", ">="]), ir.Name("x"), ir.Const(rng.choice(SMALL), "int"))
    body = [ir.If(cond, (ir.Return(ir.Const(rng.choice(SMALL), "int")),), ())]
    if rng.random() < 0.4:
        body.append(ir.Return(ir.Const(rng.choice(SMALL), "int")))  # sometimes a final return
    return _fn(name, [("x", "int")], "int", body)


def _range_loop(name, rng):
    # range(a, n) with small, possibly empty/negative bounds
    a = ir.Const(rng.choice([0, 1, -1, 2]), "int")
    inner = [ir.Assign("s", ir.BinOp("+", ir.Name("s"), ir.Const(1, "int")))]
    body = [ir.Assign("s", ir.Const(0, "int")), ir.For("i", a, ir.Name("n"), tuple(inner)), ir.Return(ir.Name("s"))]
    return _fn(name, [("n", "int")], "int", body)


def _type_error(name, rng):
    # expressions that raise TypeError in real Python (str/list where an int is needed);
    # the interpreter must raise too, not int()-coerce or mis-model them
    exprs = [
        ir.Subscript(ir.Name("xs"), ir.Name("s")),        # list indexed by a str
        ir.UnaryOp("-", ir.Name("s")),                    # -str
        ir.BinOp("+", ir.Name("s"), ir.Const(1, "int")),  # str + int
        ir.BinOp("+", ir.Name("xs"), ir.Const(1, "int")),  # list + int
        ir.BinOp("+", ir.Name("s"), ir.Name("xs")),       # str + list
        ir.BinOp("*", ir.Name("s"), ir.Name("s")),        # str * str
    ]
    return _fn(name, [("xs", "list[int]"), ("s", "str")], "int", [ir.Return(rng.choice(exprs))])


FAMILIES = [_index_list, _index_str, _index_loop, _expr, _loop, _reduce, _reduce_computed,
            _str_concat, _str_count, _list_map, _seq_truth, _falloff, _range_loop, _type_error]


def _gen_arg(rng, type_name):
    if type_name == "list[int]":
        return [rng.choice(SMALL) for _ in range(rng.randint(0, BOUND))]
    if type_name == "str":
        return "".join(rng.choice(STR_CHARS) for _ in range(rng.randint(0, BOUND)))
    # small, and within [-BOUND, BOUND] so it is also valid as a loop count
    return rng.choice([0, 1, -1, 2, 3, -2, 4, -3, 5, -5])


def run(trials: int = 3000, seed: int = 0, inputs: int = 8, report=lambda _m: None) -> int:
    """Generate `trials` functions; return the count of interpreter-vs-Python mismatches
    (fall-off-the-end, which Congruent models as an error by design, is not counted)."""
    rng = random.Random(seed)
    mismatches = 0
    for _ in range(trials):
        fn = rng.choice(FAMILIES)("f", rng)
        src = to_source(fn)
        for _ in range(inputs):
            args = [_gen_arg(rng, p.type_name) for p in fn.params]
            diff = _diff_outcome(fn, args)
            if diff[0] == "oob":
                continue  # input outside the bounded domain
            real = _real_outcome(src, "f", args)
            if real == diff or (real == ("none",) and diff[0] == "err"):
                continue  # match, or the documented fall-off-the-end model
            mismatches += 1
            report(f"MISMATCH args={args} real={real} diff={diff}\n{src}")
    return mismatches


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    mismatches = run(args.trials, args.seed, report=print)
    print(f"{args.trials} functions: {mismatches} interpreter-vs-Python mismatch(es)")
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
