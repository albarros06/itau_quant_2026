"""Regression test: `approve`/`reject` must accept the abbreviated proposal id
printed by `bootstrap`/`status` (first 8 chars), not just the full UUID."""

from __future__ import annotations

import pytest

from ops_agent.cli import _resolve_proposal_id


class _FakeRepo:
    def __init__(self, ids):
        self._ids = ids

    def list_proposals(self):
        return [{"id": i} for i in self._ids]


class _FakeAgent:
    def __init__(self, ids):
        self.repo = _FakeRepo(ids)


def test_resolves_a_unique_short_prefix_to_the_full_id():
    agent = _FakeAgent(["aa78f10410944fa3bef68c719cfdea37"])
    assert _resolve_proposal_id(agent, "aa78f104") == "aa78f10410944fa3bef68c719cfdea37"


def test_accepts_the_full_id_unchanged():
    agent = _FakeAgent(["aa78f10410944fa3bef68c719cfdea37"])
    assert (
        _resolve_proposal_id(agent, "aa78f10410944fa3bef68c719cfdea37")
        == "aa78f10410944fa3bef68c719cfdea37"
    )


def test_raises_for_no_match():
    agent = _FakeAgent(["aa78f10410944fa3bef68c719cfdea37"])
    with pytest.raises(LookupError, match="no proposal"):
        _resolve_proposal_id(agent, "deadbeef")


def test_raises_for_an_ambiguous_prefix():
    agent = _FakeAgent(["aa78f10410944fa3bef68c719cfdea37", "aa78f1049999999999999999999999999"])
    with pytest.raises(LookupError, match="ambiguous"):
        _resolve_proposal_id(agent, "aa78f104")
