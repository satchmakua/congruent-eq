"""Maximum of a non-empty list — a wrong accumulator initializer.

The rewrite seeds the running maximum with 0 instead of the first element. It
looks fine on the usual test data but is wrong for an all-negative list.
Exercises a precondition, list indexing, iteration, and a branch all at once.
"""

from congruent import assume

TITLE = "Maximum of a list"
STORY = "Rewrite seeds the running max at 0 instead of xs[0]; wrong for all-negative lists."
EXPECTED = "COUNTEREXAMPLE"


def original(xs: list[int]) -> int:
    assume(len(xs) > 0)
    m = xs[0]
    for x in xs:
        if x > m:
            m = x
    return m


def candidate(xs: list[int]) -> int:
    assume(len(xs) > 0)
    m = 0
    for x in xs:
        if x > m:
            m = x
    return m
