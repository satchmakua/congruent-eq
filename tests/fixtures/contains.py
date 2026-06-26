"""Equivalent fixture: membership via early return vs. a found-flag.

A common refactor — replace a loop that sets a `found` flag with one that
returns as soon as it finds the target (or vice versa). Equal for every list up
to the bound. Exercises `return` inside a loop (M4).
"""

EXPECTED = "EQUIVALENT"
NOTE = "early-return search vs. flag accumulation; equal for lists up to the bound"


def original(xs: list[int], t: int) -> bool:
    for x in xs:
        if x == t:
            return True
    return False


def candidate(xs: list[int], t: int) -> bool:
    found = False
    for x in xs:
        if x == t:
            found = True
    return found
