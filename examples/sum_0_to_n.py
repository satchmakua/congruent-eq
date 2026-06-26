"""Sum 0..n — accumulating loop vs. Gauss's closed form.

A real performance refactor: replace the O(n) loop with the O(1) closed form.
Valid for n >= 0 (declared with `assume`); proven up to the loop bound.
"""

from congruent import assume

TITLE = "Sum 0..n"
STORY = "Replace an accumulating loop with Gauss's closed form n*(n+1)//2."
EXPECTED = "EQUIVALENT"


def original(n: int) -> int:
    assume(n >= 0)
    total = 0
    for i in range(n + 1):
        total = total + i
    return total


def candidate(n: int) -> int:
    return n * (n + 1) // 2
