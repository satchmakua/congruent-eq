# Live runs: real models, caught and corrected

Two live sessions against the Anthropic API, captured verbatim on 2026-07-13.
Part 1 is the README's closed-loop demo run live. Part 2 points the loop at a
realistic-scale function — and includes a failure the first session exposed,
because that failure is the tool working as designed.

| | |
| --- | --- |
| Model | `claude-opus-4-8` (the repo default; see `congruent.refine.DEFAULT_MODEL`) |
| SDK / solver | `anthropic` 0.116.0, `z3-solver` 4.16.0.0, Python 3.11.9 |
| Platform | Windows 11 |

---

## Part 1 — the closed-loop demo, live

Command: `python examples/closed_loop_demo.py --live`

What to notice, in order:

1. **Scenario 2 is the whole pitch happening for real.** Asked to simplify an
   overflow-safe midpoint, the live model proposed `(a + b) // 2` — the classic
   bug. Congruent answered with the exact failing input at the configured 8-bit
   width (`a=1, b=127` → original `64`, rewrite `-64`), fed it back, and the
   model's next attempt reverted to the safe form — which Congruent then proved
   equivalent **over all 8-bit inputs** (the pair is loop-free, so the check is
   complete at that width, not merely bounded).
2. **Scenario 1 shows the other honest outcome.** The model produced the correct
   closed form on its first try, and the loop's answer is a proof rather than a
   shrug — the loop's value does not depend on the model failing.
3. **Nothing here is scripted.** The offline mode of the same demo replays canned
   attempts; `--live` sends real prompts to the API and verifies whatever comes
   back. (Model behavior varies run to run; an earlier run the same day produced
   the same round-1 overflow proposal.)

```text
Congruent closed loop — AI proposes, Congruent verifies, counterexamples feed back.
Mode: LIVE (Anthropic API)

==============================================================================
Loop → closed form
------------------------------------------------------------------------------
A real model (claude-opus-4-8) is asked to replace the loop with an equivalent closed-form expression. Congruent verifies each attempt; any counterexample is fed back until a rewrite is proven equivalent.

  original:
      def total(n: int) -> int:
          assume(n >= 0)
          s = 0
          for i in range(n + 1):
              s = s + i
          return s

  ── round 1: the LLM proposes ──
  candidate:
      def total(n: int) -> int:
          assume(n >= 0)
          return n * (n + 1) // 2
    ✓ Congruent: EQUIVALENT — proven (holds within bound: loops up to 8 iterations)

  RESULT: verified equivalent in 1 round(s). The loop only accepts a *proven* rewrite.

==============================================================================
Binary-search midpoint (the classic overflow trap)
------------------------------------------------------------------------------
A real model (claude-opus-4-8) is asked to simplify the midpoint computation. Congruent verifies each attempt; any counterexample is fed back until a rewrite is proven equivalent.

  original:
      def mid(a: int, b: int) -> int:
          return a + (b - a) // 2

  ── round 1: the LLM proposes ──
  candidate:
      def mid(a: int, b: int) -> int:
          return (a + b) // 2
    ✗ Congruent: COUNTEREXAMPLE at a=1, b=127 → original=64, rewrite=-64
      (fed back to the LLM for the next round)

  ── round 2: the LLM proposes ──
  candidate:
      def mid(a: int, b: int) -> int:
          return a + (b - a) // 2
    ✓ Congruent: EQUIVALENT — proven (complete: agree on all 8-bit inputs (no loops to bound))

  RESULT: verified equivalent in 2 round(s). The loop only accepts a *proven* rewrite.

==============================================================================
2/2 rewrites proven equivalent through the loop.
```

---

## Part 2 — realistic scale: a ~50-line billing routine

Command: `python examples/live_rewrite.py examples/water_bill.py:original`

The target is [`examples/water_bill.py`](../examples/water_bill.py) — a
tiered water-utility bill: a validation/aggregation loop, four rate blocks,
ordered percentage and flat adjustments, a minimum charge. The kind of function
a coding agent gets pointed at daily, where a boundary or rounding slip costs
real money.

### The first session failed — and that is the design working

In the first live session the model made a *semantically correct* Python
simplification: it deleted the `d = 0` initializer before the loop, which looks
dead (`d` is always reassigned before use). Congruent's v1 symbolic stage
declines to model loop-carried temporaries that are not initialized before the
loop, so every round came back:

```text
UNKNOWN  (stage: difftest)
  no counterexample found up to bound 8 (not a proof)
  note: ... (symbolic stage declined: variable(s) ['d'] assigned in a loop
        but not initialized before it)

...

NOT verified after 4 round(s), 16.9s wall-clock (final status: UNKNOWN).
```

Two things happened there. The good one: **the loop refused, four times, to
accept a rewrite it could not prove** — an `UNKNOWN` is never upgraded, so the
session ended `NOT verified`, exit code 1. The bad one: the feedback sent back
to the model said only "the bounded check was inconclusive," even though the
verdict itself recorded exactly why. The model, told nothing actionable,
re-proposed the same unprovable form every round.

That gap got fixed in `refine.py` before the second session: UNKNOWN feedback
now relays the verifier's stated reason (pinned by
`test_unknown_feedback_relays_the_verifiers_reason` in `tests/test_refine.py`).

### The second session, verbatim

Round 1: the model again deletes the "dead" initializer — and this time the
feedback tells it why that can't be verified. Round 2: it restores `d = 0`,
keeps its actual simplifications (merged tier arithmetic, a ternary minimum
charge), and the rewrite is **proven equivalent at bound 8 in 8.2 seconds of
total wall-clock, model latency included** (the two Z3 solves are milliseconds).

```text
Live rewrite of examples/water_bill.py:original
model: claude-opus-4-8   bound: 8   ints: 32-bit

── round 1  (model latency: 3.9s) ──
  candidate:
      def original(readings: list[int], senior: bool, autopay: bool) -> int:
          if len(readings) == 0:
              return 500
          total = 0
          peak_days = 0
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
  verdict:
    UNKNOWN  (stage: difftest)
      no counterexample found up to bound 8 (not a proof)
      note: 32-bit two's-complement integers
      note: no counterexample found by differential testing; equivalence not proven (symbolic stage declined: variable(s) ['d'] assigned in a loop but not initialized before it)

── round 2  (model latency: 4.0s) ──
  candidate:
      def original(readings: list[int], senior: bool, autopay: bool) -> int:
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
  verdict:
    EQUIVALENT  (stage: symbolic, 0.00s)
      equivalent up to bound 8
      note: 32-bit two's-complement integers
      note: holds within bound: lists/strings up to length 8, loops up to 8 iterations

VERIFIED in 2 round(s), 8.2s wall-clock (model + verification). The loop only accepts a proven rewrite.
```

The verified rewrite is committed as the `candidate` in
[`examples/water_bill.py`](../examples/water_bill.py), so the gallery and test
suite re-prove it on every run.
