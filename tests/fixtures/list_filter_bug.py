"""Counterexample fixture: filtering a list with a `>`/`>=` bug.

The candidate keeps zero (`>=`) where the original drops it (`>`), so the two
produce different lists for any input containing 0.
"""

EXPECTED = "COUNTEREXAMPLE"
NOTE = "keep x > 0 vs x >= 0; diverges on a list containing 0"


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
