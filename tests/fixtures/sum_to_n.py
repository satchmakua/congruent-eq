"""Equivalent fixture: closed form vs. accumulating loop.

For n >= 0 the Gauss closed form and the running sum agree. Exercises bounded
loop unrolling (the loop runs up to `n`, bounded by the unroll depth) against
straight-line arithmetic. Within the bound, Congruent should return EQUIVALENT.
"""

EXPECTED = "EQUIVALENT"
NOTE = "Gauss closed form vs. for-range accumulation; equivalent for 0 <= n <= bound"


def original(n: int) -> int:
    return n * (n + 1) // 2


def candidate(n: int) -> int:
    total = 0
    for i in range(n + 1):
        total = total + i
    return total
