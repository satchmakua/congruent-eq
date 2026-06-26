"""Equivalent fixture: len(xs) equals counting the elements one by one.

Exercises both `len(...)` and `for x in xs` iteration, and proves they agree
for every list up to the length bound.
"""

EXPECTED = "EQUIVALENT"
NOTE = "len(xs) vs. manual element count; equal for lists up to the bound"


def original(xs: list[int]) -> int:
    return len(xs)


def candidate(xs: list[int]) -> int:
    count = 0
    for _x in xs:
        count = count + 1
    return count
