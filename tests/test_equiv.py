"""Pipeline tests driven by the fixture eval set (see fixtures/README.md).

M0 guarantees from the differential stage:
  - counterexample pairs are caught (status COUNTEREXAMPLE),
  - equivalent pairs are never falsely disproven (status not COUNTEREXAMPLE).
Proving equivalence (status EQUIVALENT) needs the symbolic stage and is xfail
until M1.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

import congruent
from congruent.equiv import Status, Verdict
from congruent.ir import parse_function

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _fixture_names() -> list[str]:
    return sorted(p.stem for p in FIXTURES_DIR.glob("*.py"))


def _load_fixture(name: str) -> object:
    spec = importlib.util.spec_from_file_location(name, FIXTURES_DIR / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _verdict_for(name: str) -> Verdict:
    source = (FIXTURES_DIR / f"{name}.py").read_text(encoding="utf-8")
    return congruent.check(
        parse_function(source, "original"),
        parse_function(source, "candidate"),
        bound=8,
    )


def _names_with(expected: str) -> list[str]:
    return [n for n in _fixture_names() if _load_fixture(n).EXPECTED == expected]


def test_package_imports() -> None:
    assert congruent.__version__
    assert hasattr(congruent, "check")


def test_verdict_model() -> None:
    v = Verdict(status=Status.EQUIVALENT, bound=8, assumptions=["32-bit ints"])
    assert v.status is Status.EQUIVALENT
    assert v.bound == 8
    assert v.counterexample is None


def test_hard_query_times_out_to_unknown_not_a_hang() -> None:
    # A symbolic-coefficient polynomial (numpy.polyval's Horner loop) unrolled at
    # 32-bit is nonlinear bitvector arithmetic — Z3 can't crack it, and without a
    # cap `check()` would hang forever (this actually happened). `timeout_ms` must
    # turn that into an honest UNKNOWN, promptly. Never a false EQUIVALENT.
    import time

    horner = (
        "def f(coeffs: list[int], x: int) -> int:\n"
        "    y = 0\n    for c in coeffs:\n        y = y * x + c\n    return y"
    )
    seeded = (
        "def f(coeffs: list[int], x: int) -> int:\n"
        "    n = len(coeffs)\n    if n == 0:\n        return 0\n"
        "    y = coeffs[0]\n    for i in range(1, n):\n        y = y * x + coeffs[i]\n    return y"
    )
    o = parse_function(horner, "f")
    c = parse_function(seeded, "f")
    start = time.perf_counter()
    verdict = congruent.check(o, c, bound=8, int_width=32, timeout_ms=1500)
    elapsed = time.perf_counter() - start

    assert verdict.status is Status.UNKNOWN
    assert verdict.status is not Status.EQUIVALENT  # a timeout is never a proof
    assert elapsed < 20.0, f"timeout not honored: took {elapsed:.1f}s"


@pytest.mark.parametrize("name", _fixture_names())
def test_fixture_is_well_formed(name: str) -> None:
    mod = _load_fixture(name)
    assert callable(mod.original)
    assert callable(mod.candidate)
    assert mod.EXPECTED in {"EQUIVALENT", "COUNTEREXAMPLE"}


@pytest.mark.parametrize("name", _fixture_names())
def test_fixture_parses(name: str) -> None:
    source = (FIXTURES_DIR / f"{name}.py").read_text(encoding="utf-8")
    assert parse_function(source, "original").params is not None
    assert parse_function(source, "candidate").params is not None


@pytest.mark.parametrize("name", _names_with("COUNTEREXAMPLE"))
def test_counterexample_fixtures_are_caught(name: str) -> None:
    verdict = _verdict_for(name)
    assert verdict.status is Status.COUNTEREXAMPLE
    assert verdict.counterexample is not None
    assert verdict.counterexample.inputs  # carries the concrete diverging input


@pytest.mark.parametrize("name", _names_with("EQUIVALENT"))
def test_equivalent_fixtures_not_falsely_disproven(name: str) -> None:
    # M0: difftest must never invent a counterexample for an equivalent pair.
    assert _verdict_for(name).status is not Status.COUNTEREXAMPLE


@pytest.mark.parametrize("name", _names_with("EQUIVALENT"))
def test_equivalent_fixtures_are_proven(name: str) -> None:
    # M1: the symbolic stage proves equivalent pairs (UNSAT).
    verdict = _verdict_for(name)
    assert verdict.status is Status.EQUIVALENT
    assert verdict.stage == "symbolic"
