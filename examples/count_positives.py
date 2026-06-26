"""Count positive elements — a `>` quietly changed to `>=`.

The kind of one-character drift an LLM introduces while "tidying up". It counts
zero as positive, so the two disagree on any list containing 0.
"""

TITLE = "Count positives"
STORY = "Rewrite uses >= instead of >, counting zero as positive."
EXPECTED = "COUNTEREXAMPLE"


def original(xs: list[int]) -> int:
    count = 0
    for x in xs:
        if x > 0:
            count = count + 1
    return count


def candidate(xs: list[int]) -> int:
    count = 0
    for x in xs:
        if x >= 0:
            count = count + 1
    return count
