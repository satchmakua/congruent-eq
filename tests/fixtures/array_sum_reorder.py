"""Equivalent fixture: accumulation order doesn't change a sum.

`total + x` vs `x + total` — fixed-width addition is commutative, so the two
agree for every list up to the length bound.
"""

EXPECTED = "EQUIVALENT"
NOTE = "total + x vs. x + total over a list; commutative"


def original(xs: list[int]) -> int:
    total = 0
    for x in xs:
        total = total + x
    return total


def candidate(xs: list[int]) -> int:
    total = 0
    for x in xs:
        total = x + total
    return total
