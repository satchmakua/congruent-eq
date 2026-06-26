"""Counterexample fixture: counting with `>` vs `>=` over a list.

The candidate counts zero as "positive". The two diverge on any list
containing 0 — differential testing finds it with the boundary list `[0]`.
"""

EXPECTED = "COUNTEREXAMPLE"
NOTE = "x > 0 vs x >= 0 while counting; diverges on a list containing 0"


def original(xs: list[int]) -> int:
    count = 0
    for x in xs:
        if x > 0:
            count = count + 1
    return count


def candidate(xs: list[int]) -> int:
    count = 0
    for x in xs:
        if x >= 0:
            count = count + 1
    return count
