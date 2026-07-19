"""Contract test: activity log is append-only (contracts/activity-log-contract.md).

1. Every SQL string literal in ``store/repository.py`` that mentions ``activity_log``
   is an INSERT or SELECT — never UPDATE/DELETE.
2. No call site anywhere under ``src/ops_agent`` passes the direct return value of a
   credential-resolution call (``resolve(...)``) into ``record_activity(...)`` — the
   log must never carry a resolved credential value (rule 5, FR-001).
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OPS_AGENT_SRC = REPO_ROOT / "src" / "ops_agent"
REPOSITORY_PATH = OPS_AGENT_SRC / "store" / "repository.py"


_SQL_KEYWORDS = ("INSERT", "SELECT", "UPDATE", "DELETE")


def _sql_literals_mentioning(table: str) -> list[str]:
    tree = ast.parse(REPOSITORY_PATH.read_text(), filename=str(REPOSITORY_PATH))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and table in node.value
        and node.value.strip().upper().startswith(_SQL_KEYWORDS)
    ]


def test_activity_log_sql_is_insert_or_select_only():
    literals = _sql_literals_mentioning("activity_log")
    assert literals, "expected at least one SQL statement referencing activity_log"
    for sql in literals:
        stripped = sql.strip().upper()
        assert stripped.startswith("INSERT") or stripped.startswith("SELECT"), (
            f"non-INSERT/SELECT statement touches activity_log: {sql!r}"
        )
        assert "UPDATE" not in stripped, f"UPDATE found in an activity_log statement: {sql!r}"
        assert "DELETE" not in stripped, f"DELETE found in an activity_log statement: {sql!r}"


def _calls_named(tree: ast.AST, name: str):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            is_match = (isinstance(func, ast.Name) and func.id == name) or (
                isinstance(func, ast.Attribute) and func.attr == name
            )
            if is_match:
                yield node


def test_record_activity_never_receives_a_resolved_credential_directly():
    violations: list[str] = []
    for path in sorted(OPS_AGENT_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for call in _calls_named(tree, "record_activity"):
            args = list(call.args) + [kw.value for kw in call.keywords]
            for arg in args:
                for sub in ast.walk(arg):
                    if isinstance(sub, ast.Call):
                        func = sub.func
                        name = func.attr if isinstance(func, ast.Attribute) else getattr(
                            func, "id", None
                        )
                        if name == "resolve":
                            violations.append(f"{path.relative_to(REPO_ROOT)}:{call.lineno}")
    assert not violations, (
        "record_activity() call site(s) pass a resolved credential value directly: "
        f"{violations}"
    )
