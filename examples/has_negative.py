"""Does the list contain a negative? — adding a `break` to short-circuit.

A faithful optimization: stop scanning once a negative is found instead of
walking the whole list. Congruent proves the early-exit version matches the full
scan for every list up to the bound (exercises `break`).
"""

TITLE = "Has a negative?"
STORY = "Short-circuit the scan with break once a negative is found."
EXPECTED = "EQUIVALENT"


def original(xs: list[int]) -> bool:
    found = False
    for x in xs:
        if x < 0:
            found = True
    return found


def candidate(xs: list[int]) -> bool:
    found = False
    for x in xs:
        if x < 0:
            found = True
            break
    return found
