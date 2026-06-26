"""Equivalent fixture: reversing a loop's iteration order preserves the sum.

Both accumulate the same multiset {0, 1, ..., n-1}, just in opposite orders.
Because fixed-width addition is associative and commutative (mod 2**width),
the results are equal for *every* n — including n <= 0, where both loops run
zero times and return 0. A genuine "loop reordering" refactor that holds for
all inputs whose loop stays within the bound.
"""

EXPECTED = "EQUIVALENT"
NOTE = "reversed accumulation order; equal for all n within the loop bound"


def original(n: int) -> int:
    total = 0
    for i in range(n):
        total = total + i
    return total


def candidate(n: int) -> int:
    total = 0
    for i in range(n):
        total = total + (n - 1 - i)
    return total
