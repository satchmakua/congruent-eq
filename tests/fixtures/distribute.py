"""Equivalent fixture: distributivity holds under modular arithmetic.

`(x + y) * 2` and `x * 2 + y * 2` are equal for *all* fixed-width integers,
because two's-complement arithmetic is arithmetic mod 2**width and
multiplication distributes over addition in that ring. A non-trivial rewrite
that is genuinely equivalent over the whole modeled domain — difftest should
never disprove it, and the symbolic stage (M1) should prove it.
"""

EXPECTED = "EQUIVALENT"
NOTE = "distributivity of * over +; holds for all fixed-width ints"


def original(x: int, y: int) -> int:
    return (x + y) * 2


def candidate(x: int, y: int) -> int:
    return x * 2 + y * 2
