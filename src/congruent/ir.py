"""AST -> normalized typed IR (pipeline stage 0).

Both the differential tester and the symbolic engine consume this IR rather
than raw `ast` nodes, so the rules of the supported v1 subset live in exactly
one place and the symbolic interpreter stays small.

Supported subset (v1 target — see ROADMAP.md M0/M1/M2):
    - `def` with type-annotated positional parameters (int, bool, list[int], ...)
    - `return`
    - `if` / `else`
    - integer & boolean arithmetic, comparison, and logical operators
    - bounded `for ... in range(...)` loops (unrolled at M2)

Anything outside the subset must raise `UnsupportedConstruct` loudly — never
silently ignored. Refusing to model a construct is what keeps verdicts honest.
"""

from __future__ import annotations

from dataclasses import dataclass


class UnsupportedConstruct(Exception):
    """Raised when source uses a construct outside the supported v1 subset."""


@dataclass(frozen=True)
class Param:
    """A typed function parameter, e.g. ``x: int`` or ``xs: list[int]``."""

    name: str
    type_name: str  # normalized: "int" | "bool" | "list[int]" | ...


@dataclass
class Function:
    """Normalized typed IR for a single function.

    `params` plus `return_type` give the difftest generator a typed signature;
    `body` is the IR statement tree the symbolic interpreter walks. The body
    node types are introduced in M0/M1 alongside the interpreter.
    """

    name: str
    params: list[Param]
    return_type: str
    body: object  # TODO(M0): typed Stmt/Expr node tree


def parse_function(source: str, name: str) -> Function:
    """Parse `source` and return the IR `Function` named `name`.

    Args:
        source: Python source text containing the target function.
        name: the function to extract.

    Raises:
        UnsupportedConstruct: the function uses a construct outside the v1 subset.
        ValueError: no function named `name` is found in `source`.
    """
    # TODO(M0): ast.parse -> locate FunctionDef -> validate subset -> lower to IR.
    raise NotImplementedError("IR lowering not yet implemented — see ROADMAP.md (M0)")
