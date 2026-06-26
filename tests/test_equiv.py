"""Tests for the equivalence pipeline.

The import/smoke tests run today. The fixture-driven equivalence tests are the
real eval set; they're marked xfail until the engine lands (M0/M1) and flip to
passing as each stage is implemented.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

import congruent
from congruent.equiv import Status, Verdict

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _fixture_modules() -> list[str]:
    return sorted(p.stem for p in FIXTURES_DIR.glob("*.py"))


def test_package_imports() -> None:
    assert congruent.__version__
    assert hasattr(congruent, "check")


def test_verdict_model() -> None:
    v = Verdict(status=Status.EQUIVALENT, bound=8, assumptions=["32-bit ints"])
    assert v.status is Status.EQUIVALENT
    assert v.bound == 8
    assert v.counterexample is None


def _load_fixture(name: str) -> object:
    spec = importlib.util.spec_from_file_location(name, FIXTURES_DIR / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", _fixture_modules())
def test_fixture_is_well_formed(name: str) -> None:
    """Every fixture follows the documented convention (see fixtures/README.md)."""
    mod = _load_fixture(name)
    assert callable(getattr(mod, "original"))
    assert callable(getattr(mod, "candidate"))
    assert mod.EXPECTED in {"EQUIVALENT", "COUNTEREXAMPLE"}


@pytest.mark.xfail(reason="engine not yet implemented — see ROADMAP.md (M0/M1)", strict=True)
@pytest.mark.parametrize("name", _fixture_modules())
def test_fixture_verdict(name: str) -> None:
    """The eval set: each fixture should produce its EXPECTED verdict."""
    mod = _load_fixture(name)
    verdict = congruent.check(mod.original, mod.candidate, bound=8)
    assert verdict.status.value == mod.EXPECTED
