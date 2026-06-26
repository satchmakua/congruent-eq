"""Counterexample fixture: an off-by-one in a loop bound.

The candidate iterates `range(n + 1)` instead of `range(n)`, so it folds in one
extra term. The two diverge as soon as the loop runs at all — differential
testing catches it at n = 1 (within the loop bound).
"""

EXPECTED = "COUNTEREXAMPLE"
NOTE = "range(n) vs range(n + 1); diverges at n = 1"


def original(n: int) -> int:
    total = 0
    for i in range(n):
        total = total + i
    return total


def candidate(n: int) -> int:
    total = 0
    for i in range(n + 1):
        total = total + i
    return total
