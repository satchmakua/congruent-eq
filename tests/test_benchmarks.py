"""Guard the headline invariant via the recall benchmark: the eval set is fully
decided and never produces an unsound verdict."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "benchmarks"))

import bench_recall  # noqa: E402


def test_no_unsound_verdicts() -> None:
    unsound = [r.name for r in bench_recall.evaluate() if not r.sound]
    assert unsound == []


def test_eval_set_is_fully_decided() -> None:
    # Every fixture resolves to exactly its expected verdict (no UNKNOWNs slipping in).
    mismatched = [(r.name, r.status) for r in bench_recall.evaluate() if r.status != r.expected]
    assert mismatched == []
