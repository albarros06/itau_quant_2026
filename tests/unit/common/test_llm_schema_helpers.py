"""Unit coverage for the schema-sanitizing helpers ``build_backend`` relies on.

The Anthropic/Gemini backends themselves need live credentials and are exercised
manually (research.md test posture: no live LLM calls in the automated suite);
these pure functions are the part that's safe and worthwhile to unit test.
"""

from __future__ import annotations

import pytest

from energy_research.common.llm import _inline_refs, _strip_unsupported, build_backend


def test_inline_refs_resolves_a_simple_ref():
    schema = {
        "type": "object",
        "properties": {"child": {"$ref": "#/$defs/Child"}},
        "$defs": {"Child": {"type": "object", "properties": {"x": {"type": "integer"}}}},
    }
    resolved = _inline_refs(schema)
    assert "$defs" not in resolved
    assert resolved["properties"]["child"] == {
        "type": "object",
        "properties": {"x": {"type": "integer"}},
    }


def test_inline_refs_resolves_refs_inside_a_list():
    schema = {
        "type": "object",
        "properties": {"items": {"type": "array", "items": {"$ref": "#/$defs/Item"}}},
        "$defs": {"Item": {"type": "string"}},
    }
    resolved = _inline_refs(schema)
    assert resolved["properties"]["items"]["items"] == {"type": "string"}


def test_inline_refs_is_a_no_op_without_defs():
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}
    assert _inline_refs(schema) == schema


def test_strip_unsupported_removes_length_constraints_but_keeps_structure():
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string", "minLength": 1, "maxLength": 50}},
    }
    stripped = _strip_unsupported(schema)
    assert "minLength" not in stripped["properties"]["name"]
    assert "maxLength" not in stripped["properties"]["name"]
    assert stripped["properties"]["name"]["type"] == "string"


def test_build_backend_rejects_unknown_backend_name():
    with pytest.raises(ValueError, match="unknown LLM backend"):
        build_backend("chatgpt", "some-model", "SOME_API_KEY")
