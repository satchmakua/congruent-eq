"""Equivalent fixture (under a precondition): closed form vs. accumulating loop.

The Gauss closed form equals the running sum 0..n — but only for `n >= 0` (a
negative `n` makes the loop empty while the closed form is nonzero) and only
while the loop stays within the bound (large `n` overflows differently). The
leading `assume(n >= 0)` declares the precondition; Congruent then proves the
pair EQUIVALENT up to the loop bound.
"""

from congruent import assume

EXPECTED = "EQUIVALENT"
NOTE = "Gauss closed form vs. for-range accumulation; requires assume(n >= 0)"


def original(n: int) -> int:
    assume(n >= 0)
    return n * (n + 1) // 2


def candidate(n: int) -> int:
    total = 0
    for i in range(n + 1):
        total = total + i
    return total
