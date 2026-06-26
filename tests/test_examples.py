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
