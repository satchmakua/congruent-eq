"""Verdict formatting — turn a `Verdict` into human-readable output.

Kept separate from the engine so the result data model stays presentation-free
and the CLI (or any other front-end) can render it however it likes.
"""

from __future__ import annotations

from congruent.equiv import Status, Verdict


def format_verdict(verdict: Verdict) -> str:
    """Render a `Verdict` as a multi-line console string."""
    lines: list[str] = []

    header = verdict.status.value
    meta: list[str] = []
    if verdict.stage:
        meta.append(f"stage: {verdict.stage}")
    if verdict.solver_time is not None:
        meta.append(f"{verdict.solver_time:.2f}s")
    if meta:
        header += f"  ({', '.join(meta)})"
    lines.append(header)

    if verdict.status is Status.EQUIVALENT:
        lines.append(f"  equivalent up to bound {verdict.bound}")
    elif verdict.status is Status.COUNTEREXAMPLE and verdict.counterexample is not None:
        cx = verdict.counterexample
        shown = ", ".join(f"{k} = {v!r}" for k, v in cx.inputs.items())
        lines.append(f"  inputs:    {shown}")
        lines.append(f"  original:  {cx.original_output!r}")
        lines.append(f"  candidate: {cx.candidate_output!r}")

    for assumption in verdict.assumptions:
        lines.append(f"  assumption: {assumption}")

    return "\n".join(lines)
