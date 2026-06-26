"""Clamp a value to [lo, hi] — nested ifs vs. one expression.

A faithful refactor: collapse the guard clauses into a single nested conditional.
Congruent proves they agree for every input at the chosen width.
"""

TITLE = "Clamp to a range"
STORY = "Collapsing nested if/else clamping into one conditional expression."
EXPECTED = "EQUIVALENT"


def original(x: int, lo: int, hi: int) -> int:
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def candidate(x: int, lo: int, hi: int) -> int:
    return lo if x < lo else (hi if x > hi else x)
