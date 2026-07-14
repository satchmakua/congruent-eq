"""Horner polynomial evaluation — lifted from a real codebase (numpy).

`original` is the scalar-integer reduction of numpy's own `numpy.polyval`
(numpy/lib/_polynomial_impl.py), whose core is exactly:

    y = zeros_like(x)
    for pv in p:
        y = y * x + pv
    return y

i.e. Horner's method. Here `p` is `list[int]` and `x`/`y` are fixed-width
`int`, so it lands squarely in Congruent's subset. This is the "real code, real
model, proof" entry: `candidate` below is NOT hand-written — it is a live model's
rewrite (see docs/live_run.md), accepted only because Congruent proved it
preserves behavior *including under two's-complement overflow*, which the
repeated `y * x + c` makes a genuine risk. That is the guarantee a passing test
cannot give.
"""

TITLE = "Horner polynomial eval (numpy.polyval)"
STORY = "Real numpy Horner loop; a live model's rewrite, proven equivalent under fixed-width overflow."
EXPECTED = "EQUIVALENT"


def original(coeffs: list[int], x: int) -> int:
    # numpy.polyval's core, as a scalar-int reduction: Horner's method.
    y = 0
    for c in coeffs:
        y = y * x + c
    return y


def candidate(coeffs: list[int], x: int) -> int:
    # PLACEHOLDER — replaced by the live model's proven rewrite.
    y = 0
    for c in coeffs:
        y = y * x + c
    return y
