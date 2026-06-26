"""Symbolic interpreter — Stage 2 core: IR -> Z3 expressions.

Symbolically execute a function over fresh symbolic inputs, walking the IR and
accumulating, for each feasible path, a path condition and an output
expression. The result is a symbolic summary the solver layer turns into an
equivalence query.

Loops and recursion are unrolled to a fixed depth `bound` (M2); paths that
would exceed the bound are reported, not silently truncated.

This is path (A) from the foundational doc §3 — a from-scratch mini symbolic
interpreter — chosen for depth of signal over leaning on existing tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from congruent.ir import Function


@dataclass
class SymbolicValue:
    """A Z3 expression paired with its IR type name."""

    expr: object       # z3.ExprRef
    type_name: str


@dataclass
class PathSummary:
    """One feasible execution path: its guard and the returned expression."""

    path_condition: object          # z3.BoolRef — conjunction of branch guards
    output: SymbolicValue


@dataclass
class FunctionSummary:
    """All feasible paths of a function plus its fresh symbolic inputs."""

    inputs: dict[str, SymbolicValue]
    paths: list[PathSummary] = field(default_factory=list)
    hit_bound: bool = False         # True if unrolling was cut off at `bound`


def summarize(function: Function, *, bound: int = 8, int_width: int = 32) -> FunctionSummary:
    """Symbolically execute `function`, returning its `FunctionSummary`.

    Args:
        function: the IR function to interpret.
        bound: unroll depth for loops/recursion and array-length bound.
        int_width: bit width for the fixed-width (bitvector) integer model,
            so overflow is modeled faithfully.

    Returns:
        A `FunctionSummary` with fresh symbolic inputs and one `PathSummary`
        per feasible path. `hit_bound` flags honest incompleteness.
    """
    # TODO(M1): create fresh Z3 symbols per param from the typed signature.
    # TODO(M1): interpret the IR body, forking on branches, unrolling to bound.
    raise NotImplementedError("symbolic interpreter not yet implemented — see ROADMAP.md (M1)")
