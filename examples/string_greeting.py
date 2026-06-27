"""Build a greeting — a swapped concatenation order.

The rewrite puts the name before the prefix, so `greet("a")` becomes `"ahi "`
instead of `"hi a"`. They differ on any non-empty name.
"""

TITLE = "Build a greeting"
STORY = 'Rewrite swaps concatenation order: name + "hi " instead of "hi " + name.'
EXPECTED = "COUNTEREXAMPLE"


def original(name: str) -> str:
    return "hi " + name


def candidate(name: str) -> str:
    return name + "hi "
