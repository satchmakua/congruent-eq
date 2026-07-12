"""Closed loop: an LLM proposes a rewrite, Congruent verifies it, and any
counterexample is fed back for another attempt — until the rewrite is *proven*
equivalent within the bound, or the round budget runs out.

This is the stretch item from ROADMAP.md M7. The LLM is pluggable via the
`Rewriter` protocol so the loop itself is testable offline:

    - `ScriptedRewriter` replays a fixed list of attempts (no network) — used by
      the demo and the tests.
    - `AnthropicRewriter` calls the real Anthropic API (needs `pip install
      congruent[llm]` and a key); the counterexample feedback goes straight into
      the prompt so the model can fix its own mistake.

The value proposition: Congruent turns "the model said it refactored this
correctly" into "this refactor is proven equivalent up to the bound, or here is
the exact input that breaks it." The loop never accepts an unverified rewrite.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from congruent.equiv import Status, Verdict, check
from congruent.ir import Function, UnsupportedConstruct, parse_function


@dataclass
class Round:
    """One turn of the loop: the candidate proposed, the verdict, and the
    feedback handed back to the rewriter for the next turn (None once verified)."""

    candidate_source: str
    verdict: Verdict
    feedback: str | None = None


@dataclass
class RewriteTask:
    """Everything a rewriter needs to propose (or repair) a candidate."""

    original_source: str
    name: str
    goal: str
    history: list[Round] = field(default_factory=list)

    @property
    def last_feedback(self) -> str | None:
        """The feedback from the most recent round, or None on the first turn."""
        return self.history[-1].feedback if self.history else None


@dataclass
class RefineResult:
    """The outcome of the loop."""

    status: Status              # EQUIVALENT once verified; else the last verdict's status
    rounds: list[Round]
    final_source: str
    verified: bool              # True iff a candidate was proven EQUIVALENT within the bound


class Rewriter(Protocol):
    """Proposes a candidate rewrite (or a repair) given the task and its history.
    Must return the full source of a function named `task.name`."""

    def __call__(self, task: RewriteTask) -> str: ...


def refine(
    original_source: str,
    name: str,
    rewriter: Rewriter,
    *,
    goal: str = "rewrite the function to be simpler or faster while preserving behavior",
    max_rounds: int = 4,
    **check_kwargs: object,
) -> RefineResult:
    """Run the propose → verify → feed-back loop.

    Each round asks `rewriter` for a candidate, parses it, and runs `check`
    against the original. A `COUNTEREXAMPLE` (or a parse/signature `ERROR`) is
    turned into feedback for the next round; `EQUIVALENT` ends the loop with a
    proof. Returns after `max_rounds` if never verified.
    """
    original = parse_function(original_source, name)
    rounds: list[Round] = []

    for _ in range(max_rounds):
        task = RewriteTask(original_source, name, goal, list(rounds))
        candidate_source = rewriter(task)
        verdict = _verify(original, candidate_source, name, check_kwargs)
        feedback = None if verdict.status is Status.EQUIVALENT else _feedback(verdict)
        rounds.append(Round(candidate_source, verdict, feedback))
        if verdict.status is Status.EQUIVALENT:
            return RefineResult(Status.EQUIVALENT, rounds, candidate_source, verified=True)

    last = rounds[-1]
    return RefineResult(last.verdict.status, rounds, last.candidate_source, verified=False)


def _verify(original: Function, candidate_source: str, name: str, check_kwargs: dict) -> Verdict:
    """Parse the candidate and check it, turning a parse/signature failure into an
    ERROR verdict (so the loop can feed the message back rather than crashing)."""
    try:
        candidate = parse_function(candidate_source, name)
    except (UnsupportedConstruct, ValueError, SyntaxError) as exc:
        return Verdict(status=Status.ERROR, bound=0, stage="parse", assumptions=[str(exc)])
    return check(original, candidate, **check_kwargs)


def _feedback(verdict: Verdict) -> str:
    """Turn a non-equivalent verdict into instructions the rewriter can act on."""
    if verdict.status is Status.COUNTEREXAMPLE and verdict.counterexample is not None:
        cx = verdict.counterexample
        args = ", ".join(f"{k}={v!r}" for k, v in cx.inputs.items())
        return (
            f"Your rewrite is NOT equivalent to the original. Congruent found a "
            f"counterexample:\n"
            f"    input:            {args}\n"
            f"    original returns: {cx.original_output!r}\n"
            f"    your rewrite:     {cx.candidate_output!r}\n"
            f"These differ. Watch for fixed-width integer overflow and off-by-one "
            f"errors. Fix your rewrite so it matches the original on every input."
        )
    if verdict.status is Status.ERROR:
        why = "; ".join(verdict.assumptions) or "it could not be parsed or has a different signature"
        return f"Your rewrite could not be checked: {why}. Return a valid function with the same signature."
    # UNKNOWN
    return (
        "Congruent could not verify your rewrite within the bound (the bounded "
        "check was inconclusive). Try a form that is easier to reason about."
    )


# --- rewriters --------------------------------------------------------------

class ScriptedRewriter:
    """A deterministic, offline stand-in for an LLM: replays `attempts` in order,
    one per round (clamped to the last). Used by the demo and tests so the loop
    runs without a network or API key."""

    def __init__(self, attempts: list[str]) -> None:
        if not attempts:
            raise ValueError("ScriptedRewriter needs at least one attempt")
        self._attempts = attempts

    def __call__(self, task: RewriteTask) -> str:
        return self._attempts[min(len(task.history), len(self._attempts) - 1)]


class AnthropicRewriter:
    """Calls the Anthropic API to propose and repair rewrites. Needs the optional
    dependency (`pip install "congruent[llm]"`) and a key (`ANTHROPIC_API_KEY`, or
    an `ant auth login` profile). The counterexample feedback is threaded into the
    prompt so the model can correct its own mistake."""

    def __init__(self, model: str = "claude-opus-4-8", max_tokens: int = 2048, client: Any = None) -> None:
        if client is None:
            try:
                import anthropic  # optional dependency, imported lazily so the core stays dependency-free
            except ImportError as exc:  # pragma: no cover - exercised only without the extra installed
                raise ImportError(
                    "the LLM closed loop needs the Anthropic SDK — install it with "
                    '`pip install "congruent[llm]"`'
                ) from exc
            client = anthropic.Anthropic()
        self._client: Any = client
        self._model = model
        self._max_tokens = max_tokens

    def __call__(self, task: RewriteTask) -> str:
        message = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=(
                "You rewrite Python functions to be simpler or faster while preserving "
                "behavior exactly, including under fixed-width (two's-complement) integer "
                "arithmetic. Reply with ONLY the rewritten function in a ```python code "
                "block — same name and signature, no prose, no tests."
            ),
            messages=[{"role": "user", "content": build_prompt(task)}],
        )
        text = next((b.text for b in message.content if b.type == "text"), "")
        return extract_function_source(text, task.name)


def build_prompt(task: RewriteTask) -> str:
    """The user-turn prompt: the goal, the original, and — on repair turns — the
    previous attempt plus Congruent's counterexample feedback."""
    parts = [f"Goal: {task.goal}.", "", "Original function:",
             "```python", task.original_source.strip(), "```"]
    if task.history:
        last = task.history[-1]
        parts += [
            "",
            "Your previous attempt:",
            "```python",
            last.candidate_source.strip(),
            "```",
            "",
            last.feedback or "It was not equivalent; try again.",
        ]
    parts += ["", f"Return the corrected `{task.name}` function only."]
    return "\n".join(parts)


_CODE_BLOCK = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)


def extract_function_source(text: str, name: str) -> str:
    """Pull the function source out of an LLM reply: prefer a fenced code block,
    else fall back to the raw text (so a bare `def` still parses)."""
    blocks = _CODE_BLOCK.findall(text)
    for block in blocks:
        if f"def {name}" in block:
            return block.strip()
    if blocks:
        return blocks[0].strip()
    return text.strip()
