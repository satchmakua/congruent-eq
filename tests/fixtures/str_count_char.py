"""Equivalent fixture: counting a character, comparison written both ways.

`ch == "a"` vs `"a" == ch` over the characters of a string — equal for every
string up to the bound. Exercises string iteration and character equality.
"""

EXPECTED = "EQUIVALENT"
NOTE = "count 'a' with ch == 'a' vs 'a' == ch over a string"


def original(s: str) -> int:
    count = 0
    for ch in s:
        if ch == "a":
            count = count + 1
    return count


def candidate(s: str) -> int:
    count = 0
    for ch in s:
        if "a" == ch:
            count = count + 1
    return count
