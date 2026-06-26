"""Keep the positive numbers — a filter that drops the wrong elements.

The rewrite uses `>=` instead of `>`, so it keeps zeros the original discards.
The two return different lists for any input containing 0. A list-in / list-out
refactor (M6).
"""

TITLE = "Keep positive numbers"
STORY = "Filter rewrite uses >= instead of >, so it keeps zeros it should drop."
EXPECTED = "COUNTEREXAMPLE"


def original(xs: list[int]) -> list[int]:
    result = []
    for x in xs:
        if x > 0:
            result = result + [x]
    return result


def candidate(xs: list[int]) -> list[int]:
    result = []
    for x in xs:
        if x >= 0:
            result = result + [x]
    return result
