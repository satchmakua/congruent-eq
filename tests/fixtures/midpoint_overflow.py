"""Counterexample fixture: the classic midpoint overflow.

`candidate` is the kind of "simplification" an LLM happily produces. Under
fixed-width (e.g. 32-bit) integers, `lo + hi` overflows for large inputs while
`lo + (hi - lo) // 2` does not, so the two diverge — Congruent should return
the concrete overflowing input.
"""

EXPECTED = "COUNTEREXAMPLE"
NOTE = "32-bit overflow in (lo + hi); breaks at large lo, hi near INT_MAX"


def original(lo: int, hi: int) -> int:
    return lo + (hi - lo) // 2


def candidate(lo: int, hi: int) -> int:
    return (lo + hi) // 2
