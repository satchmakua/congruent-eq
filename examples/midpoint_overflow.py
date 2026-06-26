"""Binary-search midpoint — the textbook overflow.

Asked to "simplify" an overflow-safe midpoint, an LLM happily rewrites it into
the classic buggy form. Under 32-bit integers the two diverge once `lo + hi`
overflows. This is the demo from the foundational doc.
"""

TITLE = "Binary-search midpoint"
STORY = "LLM 'simplifies' lo + (hi - lo)//2 into (lo + hi)//2; overflows at 32 bits."
EXPECTED = "COUNTEREXAMPLE"


def original(lo: int, hi: int) -> int:
    return lo + (hi - lo) // 2


def candidate(lo: int, hi: int) -> int:
    return (lo + hi) // 2
