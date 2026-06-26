"""Equivalent fixture: a conditional expression rewritten as if/else.

The same absolute-value logic written two ways. Equal for every fixed-width
input — including INT_MIN, where `-x` overflows back to INT_MIN in *both*
functions, so they still agree. Exercises branches and early return in the
differential stage; the symbolic stage (M1) should prove equivalence.
"""

EXPECTED = "EQUIVALENT"
NOTE = "ternary vs if/else absolute value; agree everywhere, incl. INT_MIN"


def original(x: int) -> int:
    return x if x >= 0 else -x


def candidate(x: int) -> int:
    if x < 0:
        return -x
    return x
