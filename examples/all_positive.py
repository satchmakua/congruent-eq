"""All elements positive? — adding a short-circuit early return.

A faithful optimization: instead of scanning the whole list into a flag, bail
out on the first non-positive element. Congruent proves the early-return version
agrees with the full scan for every list up to the bound (exercises `return`
inside a loop).
"""

TITLE = "All positive?"
STORY = "Short-circuit the all-positive check by returning False on the first failure."
EXPECTED = "EQUIVALENT"


def original(xs: list[int]) -> bool:
    ok = True
    for x in xs:
        if x <= 0:
            ok = False
    return ok


def candidate(xs: list[int]) -> bool:
    for x in xs:
        if x <= 0:
            return False
    return True
