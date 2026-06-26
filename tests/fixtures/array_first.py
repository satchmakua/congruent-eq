"""Equivalent fixture: "first element, or 0 if empty", written two ways.

Both guard the `xs[0]` access with a length check, so the index is always in
bounds — the symbolic stage proves them equal (including matching the empty-list
case) now that list indexing is modeled in proofs.
"""

EXPECTED = "EQUIVALENT"
NOTE = "guarded xs[0] vs. guarded xs[0]; equal incl. the empty list"


def original(xs: list[int]) -> int:
    if len(xs) > 0:
        return xs[0]
    return 0


def candidate(xs: list[int]) -> int:
    result = 0
    if 0 < len(xs):
        result = xs[0]
    return result
