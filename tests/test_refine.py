"""Tests for the closed-loop refinement harness (the LLM ↔ Congruent loop).

The LLM is stubbed so these run offline and deterministically: a `ScriptedRewriter`
replays fixed attempts, and a tiny fake Anthropic client exercises the API path
without a network call.
"""

from __future__ import annotations

from congruent.equiv import Status
from congruent.refine import (
    AnthropicRewriter,
    RewriteTask,
    ScriptedRewriter,
    build_prompt,
    extract_function_source,
    refine,
)

_SUM = (
    "def total(n: int) -> int:\n"
    "    assume(n >= 0)\n"
    "    s = 0\n"
    "    for i in range(n + 1):\n"
    "        s = s + i\n"
    "    return s"
)


def test_loop_feeds_counterexample_back_then_verifies() -> None:
    # First attempt is off by one (wrong for every n); second is correct.
    attempts = [
        "def total(n: int) -> int:\n    return n * n // 2",
        "def total(n: int) -> int:\n    return n * (n + 1) // 2",
    ]
    result = refine(_SUM, "total", ScriptedRewriter(attempts), bound=8, int_width=32)

    assert result.verified
    assert result.status is Status.EQUIVALENT
    assert len(result.rounds) == 2
    # round 1 found a counterexample and produced feedback for round 2
    assert result.rounds[0].verdict.status is Status.COUNTEREXAMPLE
    assert result.rounds[0].feedback is not None and "counterexample" in result.rounds[0].feedback
    # round 2 was proven equivalent and left no feedback
    assert result.rounds[1].verdict.status is Status.EQUIVALENT
    assert result.rounds[1].feedback is None
    assert result.final_source == attempts[1]


def test_catches_the_midpoint_overflow_rewrite() -> None:
    # (a + b) // 2 overflows fixed width; the safe form does not.
    original = "def mid(a: int, b: int) -> int:\n    return a + (b - a) // 2"
    attempts = [
        "def mid(a: int, b: int) -> int:\n    return (a + b) // 2",
        "def mid(a: int, b: int) -> int:\n    return a + (b - a) // 2",
    ]
    result = refine(original, "mid", ScriptedRewriter(attempts), bound=4, int_width=8)
    assert result.verified
    assert result.rounds[0].verdict.status is Status.COUNTEREXAMPLE  # overflow caught


def test_an_immediately_correct_rewrite_verifies_in_one_round() -> None:
    good = "def total(n: int) -> int:\n    return n * (n + 1) // 2"
    result = refine(_SUM, "total", ScriptedRewriter([good]), bound=8, int_width=32)
    assert result.verified
    assert len(result.rounds) == 1


def test_a_persistently_wrong_rewriter_is_never_falsely_verified() -> None:
    # The loop must never report `verified` for a rewrite that stays wrong.
    bad = "def total(n: int) -> int:\n    return n * n // 2"
    result = refine(_SUM, "total", ScriptedRewriter([bad]), max_rounds=3, bound=8, int_width=32)
    assert not result.verified
    assert result.status is Status.COUNTEREXAMPLE
    assert len(result.rounds) == 3  # tried the full budget


def test_a_parse_error_becomes_actionable_feedback() -> None:
    attempts = [
        "def total(n: int) -> int:\n    return n <<>> 2",   # not valid Python
        "def total(n: int) -> int:\n    return n * (n + 1) // 2",
    ]
    result = refine(_SUM, "total", ScriptedRewriter(attempts), bound=8, int_width=32)
    assert result.rounds[0].verdict.status is Status.ERROR
    assert result.rounds[0].feedback is not None
    assert result.verified  # recovered on the second attempt


def test_extract_function_source_prefers_the_named_code_block() -> None:
    reply = (
        "Here's the fix:\n\n"
        "```python\n"
        "def helper(x):\n    return x\n"
        "```\n\n"
        "and the function you asked for:\n\n"
        "```python\n"
        "def total(n: int) -> int:\n    return n * (n + 1) // 2\n"
        "```\n"
    )
    src = extract_function_source(reply, "total")
    assert src.startswith("def total")
    assert "n * (n + 1) // 2" in src


def test_build_prompt_includes_feedback_on_repair_turns() -> None:
    task = RewriteTask(_SUM, "total", "simplify")
    first = build_prompt(task)
    assert "Original function" in first and "previous attempt" not in first

    from congruent.equiv import Counterexample, Verdict
    from congruent.refine import Round, _feedback

    cx_verdict = Verdict(
        status=Status.COUNTEREXAMPLE, bound=8,
        counterexample=Counterexample(inputs={"n": 1}, original_output=1, candidate_output=0),
    )
    task.history.append(Round("def total(n): return 0", cx_verdict, _feedback(cx_verdict)))
    repair = build_prompt(task)
    assert "previous attempt" in repair and "counterexample" in repair


class _FakeBlock:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class _FakeMessage:
    def __init__(self, text: str) -> None:
        self.content = [_FakeBlock(text)]


class _FakeMessages:
    def __init__(self, reply: str) -> None:
        self._reply = reply
        self.calls: list[dict] = []

    def create(self, **kwargs: object) -> _FakeMessage:
        self.calls.append(kwargs)
        return _FakeMessage(self._reply)


class _FakeClient:
    def __init__(self, reply: str) -> None:
        self.messages = _FakeMessages(reply)


def test_anthropic_rewriter_drives_the_loop_through_a_fake_client() -> None:
    # No network: a fake client returns a correct rewrite in a code block.
    reply = "```python\ndef total(n: int) -> int:\n    return n * (n + 1) // 2\n```"
    rewriter = AnthropicRewriter(client=_FakeClient(reply))
    result = refine(_SUM, "total", rewriter, bound=8, int_width=32)
    assert result.verified
    assert rewriter._client.messages.calls  # the client was actually invoked
