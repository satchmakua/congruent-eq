"""Pin every gallery example to its declared verdict, so the demo can't rot."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))

import run_gallery  # noqa: E402


def test_gallery_matches_expected() -> None:
    mismatched = [
        (o.name, o.expected, o.status)
        for o in run_gallery.evaluate()
        if o.status != o.expected
    ]
    assert mismatched == []


def test_closed_loop_demo_verifies_offline() -> None:
    # The stretch demo (examples/closed_loop_demo.py) must converge in offline mode:
    # every scripted scenario ends in a proven-equivalent rewrite (main() returns 0).
    import closed_loop_demo  # noqa: E402  (examples dir is already on sys.path)

    assert closed_loop_demo.main([]) == 0


_WATER_BILL = Path(__file__).resolve().parent.parent / "examples" / "water_bill.py"


def test_live_rewrite_extracts_the_named_function() -> None:
    # live_rewrite.py backs a documented command (`live_rewrite.py FILE.py:func`);
    # its source-extraction is pure logic and must not rot silently, even though
    # the surrounding loop is network-only.
    import live_rewrite  # noqa: E402  (examples dir is already on sys.path)

    src = live_rewrite._extract_function(_WATER_BILL, "original")
    assert src.startswith("def original(")
    assert "for r in readings:" in src  # the whole body, not just the signature


def test_live_rewrite_reports_a_missing_function() -> None:
    import live_rewrite  # noqa: E402
    import pytest

    with pytest.raises(SystemExit):
        live_rewrite._extract_function(_WATER_BILL, "nope")
