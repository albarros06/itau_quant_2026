"""Contract test: architecture boundaries (contracts/architecture-boundaries.md).

Runs import-linter against the contracts declared in pyproject.toml, making a layer
violation a failing test, not a review-time observation.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_import_linter_contracts_hold():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "importlinter.cli",
            "lint_imports",
            "--config",
            str(REPO_ROOT / "pyproject.toml"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "architecture boundary contract violated:\n" + result.stdout + result.stderr
    )


def test_all_required_contracts_are_declared():
    """The four contracts from architecture-boundaries.md must all be present."""
    with open(REPO_ROOT / "pyproject.toml", "rb") as fh:
        pyproject = tomllib.load(fh)
    contracts = pyproject["tool"]["importlinter"]["contracts"]
    types = [c["type"] for c in contracts]
    assert "layers" in types, "layers contract missing"
    forbidden = [c for c in contracts if c["type"] == "forbidden"]
    sources = {m for c in forbidden for m in c["source_modules"]}
    assert "energy_research.datastore" in sources, "datastore-upstream contract missing"
    assert "energy_research" in sources, "broker/execution forbidden contract missing"

    layers_contract = next(c for c in contracts if c["type"] == "layers")
    sibling_layer = next(layer for layer in layers_contract["layers"] if "|" in layer)
    for member in ("generation", "screening", "backtesting", "critique", "reporting"):
        assert f"energy_research.{member}" in sibling_layer, (
            f"{member} must be in the independent sibling group"
        )


def test_no_broker_package_installed():
    """Structural exclusion: no broker/execution package may even be importable."""
    for pkg in ("ib_insync", "ibapi", "ccxt", "alpaca", "MetaTrader5", "kiteconnect"):
        result = subprocess.run([sys.executable, "-c", f"import {pkg}"], capture_output=True)
        assert result.returncode != 0, f"broker/execution package {pkg} is installed"
