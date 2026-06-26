"""Counterexample fixture: the classic `<=` -> `<` off-by-one.

An LLM "tidies up" a boundary check and silently flips inclusive to exclusive.
The two agree everywhere except at x == 0, which differential testing hits
immediately (0 is a boundary value). Congruent should return that input.
"""

EXPECTED = "COUNTEREXAMPLE"
NOTE = "<= changed to <; diverges at x == 0"


def original(x: int) -> int:
    return 1 if x <= 0 else 0


def candidate(x: int) -> int:
    return 1 if x < 0 else 0
