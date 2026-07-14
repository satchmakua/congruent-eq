"""Utility billing at realistic scale — a live model's rewrite, proven.

Every other gallery entry is a handful of lines. This one is the shape of real
legacy code: a ~50-line billing routine with a validation loop, tiered rate
blocks, ordered adjustments, and a minimum charge — the kind of function a
coding agent gets pointed at every day, where "looks right" is worthless and
a boundary or rounding slip costs real money.

The candidate below was NOT written by hand: it is the rewrite a live model
produced through the closed loop (`python examples/live_rewrite.py
examples/water_bill.py:original`), verified by Congruent before being accepted.
The unedited session transcript, with timing, is in docs/live_run.md.
"""

TITLE = "Water-utility bill (realistic scale)"
STORY = "A ~50-line tiered-billing routine; the candidate is a live LLM rewrite, accepted only after proof."
EXPECTED = "EQUIVALENT"


def original(readings: list[int], senior: bool, autopay: bool) -> int:
    """Monthly water bill in cents from daily meter readings.

    Real-world billing shape: validate the frame, aggregate consumption,
    price it in tiered blocks, apply adjustments in a contractual order,
    and enforce a minimum charge. Money is integer cents; every division
    is floor division.
    """
    # -- validate & aggregate ------------------------------------------
    if len(readings) == 0:
        return 500                      # no data: bill the minimum charge
    total = 0
    peak_days = 0
    d = 0                               # v1 symbolic stage: loop temps init before the loop
    for r in readings:
        if r < 0:
            return -1                   # corrupted frame: reject the bill
        d = r if r < 5000 else 5000     # meter hardware caps a day at 5,000 gal
        if d > 3000:
            peak_days = peak_days + 1   # demand surcharge past 3,000 gal/day
        total = total + d

    # -- tiered consumption blocks (cents per gallon) -------------------
    t1 = total if total < 1000 else 1000        # first 1,000 gal @ 3c
    charge = t1 * 3
    rest = total - t1
    t2 = rest if rest < 4000 else 4000          # next 4,000 gal @ 5c
    charge = charge + t2 * 5
    rest = rest - t2
    t3 = rest if rest < 15000 else 15000        # next 15,000 gal @ 8c
    charge = charge + t3 * 8
    rest = rest - t3
    charge = charge + rest * 12                 # everything above @ 12c

    # -- demand surcharge ------------------------------------------------
    charge = charge + peak_days * 200           # 200c per peak day

    # -- adjustments (order is contractual: discount, then credit) -------
    if senior:
        # 15% discount, floored so rounding never favors the utility
        charge = charge - charge * 15 // 100
    if autopay:
        charge = charge - 150                   # flat autopay credit
        if charge < 0:
            charge = 0

    # -- minimum charge ---------------------------------------------------
    if charge < 500:
        charge = 500
    return charge


# The live model's proven rewrite (claude-opus-4-8, 2026-07-13), verbatim from
# the session in docs/live_run.md except the function name, which the gallery
# runner requires to be `candidate`.
def candidate(readings: list[int], senior: bool, autopay: bool) -> int:
    if len(readings) == 0:
        return 500
    total = 0
    peak_days = 0
    d = 0
    for r in readings:
        if r < 0:
            return -1
        d = r if r < 5000 else 5000
        if d > 3000:
            peak_days = peak_days + 1
        total = total + d

    t1 = total if total < 1000 else 1000
    charge = t1 * 3
    rest = total - t1
    t2 = rest if rest < 4000 else 4000
    charge = charge + t2 * 5
    rest = rest - t2
    t3 = rest if rest < 15000 else 15000
    charge = charge + t3 * 8 + (rest - t3) * 12

    charge = charge + peak_days * 200

    if senior:
        charge = charge - charge * 15 // 100
    if autopay:
        charge = charge - 150
        if charge < 0:
            charge = 0

    return charge if charge >= 500 else 500
