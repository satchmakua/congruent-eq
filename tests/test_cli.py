"""CLI contract tests — the surface users actually run.

The exit codes are a documented interface (0 EQUIVALENT / 1 COUNTEREXAMPLE /
2 UNKNOWN|ERROR): scripts and CI depend on them, so they are pinned here. The
timeout test is the important one — without `--timeout` the CLI could spin
forever on an intractable query instead of reporting UNKNOWN.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from congruent import cli

_REPO = Path(__file__).resolve().parent.parent
_FIXTURES = _REPO / "tests" / "fixtures"
_EXAMPLES = _REPO / "examples"


def _spec(path: Path, func: str) -> str:
    return f"{path}:{func}"


def test_equivalent_pair_exits_zero(capsys) -> None:
    src = _FIXTURES / "sum_to_n.py"
    code = cli.main([_spec(src, "original"), _spec(src, "candidate")])
    assert code == 0
    assert "EQUIVALENT" in capsys.readouterr().out


def test_counterexample_pair_exits_one(capsys) -> None:
    src = _FIXTURES / "midpoint_overflow.py"
    code = cli.main([_spec(src, "original"), _spec(src, "candidate")])
    assert code == 1
    out = capsys.readouterr().out
    assert "COUNTEREXAMPLE" in out
    assert "inputs:" in out  # the concrete diverging input is shown


def test_intractable_query_times_out_to_unknown_and_exits_two(capsys) -> None:
    # polyval's `y = y*x + c` at 32-bit is a symbolic-coefficient polynomial —
    # nonlinear bitvector arithmetic Z3 cannot crack. Before `--timeout` this
    # hung the CLI indefinitely. It must now report UNKNOWN, promptly.
    src = _EXAMPLES / "polyval.py"
    start = time.perf_counter()
    code = cli.main([_spec(src, "original"), _spec(src, "candidate"),
                     "--int-width", "32", "--bound", "8", "--timeout", "3"])
    elapsed = time.perf_counter() - start

    assert code == 2
    out = capsys.readouterr().out
    assert "UNKNOWN" in out
    assert "EQUIVALENT" not in out  # a timeout is never upgraded to a proof
    assert elapsed < 30.0, f"--timeout not honored: took {elapsed:.1f}s"


def test_output_survives_a_legacy_windows_code_page() -> None:
    # A string counterexample decodes to arbitrary code points (solver._decode_seq
    # does chr(e) over the full range), and Windows consoles default to cp1252 —
    # which cannot encode most of them. main() reconfigures stdout to UTF-8 so a
    # real verdict prints instead of dying with UnicodeEncodeError.
    src = _FIXTURES / "str_concat_order.py"
    proc = subprocess.run(
        [sys.executable, "-m", "congruent.cli", _spec(src, "original"), _spec(src, "candidate")],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
        cwd=str(_REPO),
    )
    assert "UnicodeEncodeError" not in proc.stderr
    assert proc.returncode == 1  # the real COUNTEREXAMPLE verdict, not a crash
    assert "COUNTEREXAMPLE" in proc.stdout


def test_missing_file_exits_two(capsys) -> None:
    code = cli.main([_spec(_FIXTURES / "does_not_exist.py", "f"),
                     _spec(_FIXTURES / "does_not_exist.py", "g")])
    assert code == 2
    assert "file not found" in capsys.readouterr().err


def test_assume_is_honored_and_reported(capsys) -> None:
    # abs_branch's two forms are both abs(): equivalent on every input, with or
    # without a precondition. What this pins is that --assume is parsed, applied,
    # and *surfaced in the verdict* — a scoped result must never read as an
    # unconditional one.
    src = _FIXTURES / "abs_branch.py"
    code = cli.main([_spec(src, "original"), _spec(src, "candidate"),
                     "--assume", "x >= 0"])
    assert code == 0
    out = capsys.readouterr().out
    assert "EQUIVALENT" in out
    assert "note: precondition: x >= 0" in out
