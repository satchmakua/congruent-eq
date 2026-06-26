"""Equivalent fixture: mapping a list, `x * 2` rewritten as `x + x`.

Both build a new list by doubling each element. A list-output refactor that
holds for every list up to the bound.
"""

EXPECTED = "EQUIVALENT"
NOTE = "map x*2 vs x+x; equal element-wise for lists up to the bound"


def original(xs: list[int]) -> list[int]:
    result = []
    for x in xs:
        result = result + [x * 2]
    return result


def candidate(xs: list[int]) -> list[int]:
    result = []
    for x in xs:
        result = result + [x + x]
    return result
