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

This entry also marks the tool's honest hard edge. The `y = y * x + c` loop
multiplies the accumulator by a *symbolic* `x` each iteration, so the proof
obligation is a polynomial whose coefficients are themselves symbolic — nonlinear
bitvector arithmetic, exactly what a bit-blasting SMT solver chokes on. It proves
in 0.7s at `BOUND = 2`, `INT_WIDTH = 8` (below), but the cost explodes with both
degree and width: bound 3 / 8-bit already takes ~18s, and 32-bit is intractable
even at bound 2 — where the solver returns an honest UNKNOWN rather than hanging
(a hang the `timeout_ms` cap in `check` now prevents). See benchmarks/README.md.
"""

TITLE = "Horner polynomial eval (numpy.polyval)"
STORY = "Real numpy Horner loop; a live model's rewrite, proven at 8-bit/bound-2 (the solver's hard case)."
EXPECTED = "EQUIVALENT"

# Proven at this width/bound in <1s; higher settings hit the nonlinear-multiply
# wall and return UNKNOWN (see the module docstring). The gallery runner reads
# these per-example overrides.
BOUND = 2
INT_WIDTH = 8


def original(coeffs: list[int], x: int) -> int:
    # numpy.polyval's core, as a scalar-int reduction: Horner's method.
    y = 0
    for c in coeffs:
        y = y * x + c
    return y


# The live model's proven rewrite (claude-opus-4-8, 2026-07-14), verbatim from the
# session in docs/live_run.md except the function name (the gallery runner requires
# `candidate`). Asked to drop the wasted `0 * x` first step, the model seeded the
# accumulator with coeffs[0] AND added the empty-list guard — without which it would
# crash on `[]` where the original returns 0. Congruent proved it preserves behavior.
def candidate(coeffs: list[int], x: int) -> int:
    n = len(coeffs)
    if n == 0:
        return 0
    y = coeffs[0]
    for i in range(1, n):
        y = y * x + coeffs[i]
    return y
