"""Counterexample fixture: string concatenation is not commutative.

`s + t` vs `t + s` — they differ whenever the two strings aren't identical.
"""

EXPECTED = "COUNTEREXAMPLE"
NOTE = "s + t vs t + s; concatenation order matters"


def original(s: str, t: str) -> str:
    return s + t


def candidate(s: str, t: str) -> str:
    return t + s
