"""Contract test: operations-agent reach boundary (contracts/ops-agent-boundary.md, FR-019).

Two mechanical checks, neither relying on review discipline:

1. The import-linter one-directional independence contract (pyproject.toml) holds:
   ``energy_research`` never imports ``ops_agent``.
2. A static reach audit: every ``energy_research.*`` module imported anywhere under
   ``src/ops_agent/`` is a prefix of an allowlist entry. A new import outside the
   allowlist fails this test, not just a future code review.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OPS_AGENT_SRC = REPO_ROOT / "src" / "ops_agent"

ALLOWLIST = [
    "energy_research.config.settings",
    "energy_research.orchestration.ingest",
    "energy_research.orchestration.cycle",
    "energy_research.datastore.repository",
    "energy_research.common.logging",
    "energy_research.common.llm",
    "energy_research.ingestion.registry",
]


def _energy_research_import_groups(path: Path) -> list[list[str]]:
    """One candidate-path group per import statement.

    `from energy_research.ingestion import registry` could be reaching the
    submodule `energy_research.ingestion.registry` OR a symbol named
    ``registry`` defined directly in ``energy_research.ingestion`` — both
    candidate forms are included, and the statement is compliant if EITHER
    matches the allowlist (an "OR" per statement, not a flat global list).
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    groups: list[list[str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("energy_research"):
                    groups.append([alias.name])
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("energy_research")
        ):
            candidates = [node.module]
            candidates.extend(f"{node.module}.{alias.name}" for alias in node.names)
            groups.append(candidates)
    return groups


def test_import_linter_independence_contract_holds():
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
        "ops_agent / energy_research independence contract violated:\n"
        + result.stdout
        + result.stderr
    )


def _is_allowed(module: str) -> bool:
    return any(module == entry or module.startswith(entry + ".") for entry in ALLOWLIST)


def test_reach_audit_matches_allowlist():
    violations: list[tuple[str, list[str]]] = []
    for path in sorted(OPS_AGENT_SRC.rglob("*.py")):
        for group in _energy_research_import_groups(path):
            if not any(_is_allowed(candidate) for candidate in group):
                violations.append((str(path.relative_to(REPO_ROOT)), group))
    assert not violations, (
        "ops_agent imports outside the FR-019 allowlist "
        f"(contracts/ops-agent-boundary.md): {violations}"
    )


def test_at_least_one_allowlisted_import_exists():
    """Sanity check that the audit above is exercising real code, not an empty tree."""
    found = [
        group
        for path in OPS_AGENT_SRC.rglob("*.py")
        for group in _energy_research_import_groups(path)
    ]
    assert found, "expected ops_agent to import something from energy_research by now"
