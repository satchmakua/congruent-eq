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


def evaluate(bound: int = 8) -> list[Outcome]:
    outcomes: list[Outcome] = []
    for path in sorted(EXAMPLES.glob("*.py")):
        if path.name in _NON_GALLERY:
            continue
        source = path.read_text(encoding="utf-8")
        module = _load(path)
        verdict = check(
            parse_function(source, "original"),
            parse_function(source, "candidate"),
            bound=bound,
        )
        outcomes.append(Outcome(path.stem, module.TITLE, module.EXPECTED, verdict.status.value))
    return outcomes


def main() -> int:
    # Windows consoles default to a legacy code page (e.g. cp1252); force UTF-8
    # so gallery titles/stories can use any character without crashing the run.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    for path in sorted(EXAMPLES.glob("*.py")):
        if path.name in _NON_GALLERY:
            continue
        source = path.read_text(encoding="utf-8")
        module = _load(path)
        verdict = check(
            parse_function(source, "original"),
            parse_function(source, "candidate"),
            bound=8,
        )
        print(f"### {module.TITLE}  ({path.name})")
        print(f"    {module.STORY}")
        for line in format_verdict(verdict).splitlines():
            print(f"    {line}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
