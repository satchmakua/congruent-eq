"""Run Congruent over the example gallery and print a narrated verdict for each.

Each example module defines `TITLE`, `STORY`, `EXPECTED`, and an `original` /
`candidate` pair. Run it:  python examples/run_gallery.py
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from congruent import check  # noqa: E402
from congruent.ir import parse_function  # noqa: E402
from congruent.report import format_verdict  # noqa: E402

EXAMPLES = Path(__file__).resolve().parent

# Runnable scripts in examples/ that are NOT gallery `original`/`candidate` pairs.
_NON_GALLERY = {"run_gallery.py", "closed_loop_demo.py", "live_rewrite.py"}

# Every check is capped so a hard query (e.g. a symbolic-coefficient polynomial,
# where bitvector multiplication blows up) returns UNKNOWN instead of hanging the
# gallery. Generous vs. the sub-second examples; see benchmarks/README.md.
_CHECK_TIMEOUT_MS = 20_000

# The gallery's default bound; an example may override it (see `_bound_width`).
_DEFAULT_BOUND = 8


def _bound_width(module, default_bound: int) -> tuple[int, int]:
    """An example may declare its own BOUND / INT_WIDTH (some pairs are only
    tractable at a smaller width/bound — e.g. polyval's nonlinear multiply)."""
    return getattr(module, "BOUND", default_bound), getattr(module, "INT_WIDTH", 32)


@dataclass
class Outcome:
    name: str
    title: str
    expected: str
    status: str


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(bound: int):
    """Solve every gallery pair once; yields (path, module, verdict). Shared by
    `evaluate` (what the tests pin) and `main` (what humans read), so the two can
    never drift apart."""
    for path in sorted(EXAMPLES.glob("*.py")):
        if path.name in _NON_GALLERY:
            continue
        source = path.read_text(encoding="utf-8")
        module = _load(path)
        b, w = _bound_width(module, bound)
        yield path, module, check(
            parse_function(source, "original"),
            parse_function(source, "candidate"),
            bound=b, int_width=w, timeout_ms=_CHECK_TIMEOUT_MS,
        )


def evaluate(bound: int = _DEFAULT_BOUND) -> list[Outcome]:
    return [
        Outcome(path.stem, module.TITLE, module.EXPECTED, verdict.status.value)
        for path, module, verdict in _run(bound)
    ]


def main() -> int:
    # Windows consoles default to a legacy code page (e.g. cp1252); force UTF-8
    # so gallery titles/stories can use any character without crashing the run.
    # (`_run` is lazy, so this happens before the first example is loaded.)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    for path, module, verdict in _run(_DEFAULT_BOUND):
        print(f"### {module.TITLE}  ({path.name})")
        print(f"    {module.STORY}")
        for line in format_verdict(verdict).splitlines():
            print(f"    {line}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
