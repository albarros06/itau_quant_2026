"""Structured-LLM transport shared by the generation and critique layers.

The architecture contract forbids ``critique`` from importing ``generation``, so the
transport both layers need lives here in ``common``. Each layer keeps its own thin,
schema-constrained adapter on top (research.md §3); this module knows nothing about
theses or critiques — it turns (system, prompt, JSON schema) into raw payloads.

Two backends, selected by configuration (Principle VI):

- ``anthropic``: real LLM calls via the Anthropic API's structured-output mode
  (``output_config.format`` with a JSON schema). Provider-side enforcement is NOT
  trusted alone — callers independently re-validate every payload (Principle III).
- ``deterministic_stub``: a fully deterministic, offline generator driven by the
  structured ``context`` of the request. Used for the labeled sample dataset and
  the test suite, and is what makes cycle replay exactly reproducible (FR-028).

Nothing in either backend executes model output; payloads are inert data.
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from typing import Any, Protocol

from energy_research.common.logging import get_logger

log = get_logger("common.llm")


@dataclass
class StructuredRequest:
    task: str  # "thesis_generation" | "critique"
    system: str
    prompt: str
    json_schema: dict
    n: int = 1
    # Structured data behind the prompt; the stub backend consumes this directly,
    # the anthropic backend relies on the rendered prompt text instead.
    context: dict = field(default_factory=dict)


class StructuredBackend(Protocol):
    def complete(self, request: StructuredRequest) -> list[Any]:
        """Return up to ``request.n`` raw payloads (unvalidated JSON-like objects)."""
        ...


def _strip_unsupported(schema: dict) -> dict:
    """Remove JSON Schema constraints the structured-output API doesn't support.

    minLength/maxLength/minItems are enforced by the caller's independent Pydantic
    re-validation, so removing them provider-side loses nothing.
    """
    schema = copy.deepcopy(schema)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key in ("minLength", "maxLength", "minItems", "maxItems"):
                node.pop(key, None)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    return schema


class AnthropicStructuredBackend:
    """Anthropic API adapter constrained to a JSON schema. One payload per call."""

    def __init__(self, model: str, api_key_env: str = "ANTHROPIC_API_KEY"):
        import anthropic  # deferred so offline (stub) runs never require the package

        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise RuntimeError(
                f"generation.backend=anthropic but env var {api_key_env} is not set; "
                "credentials are referenced by env-var name only (never in config)"
            )
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def complete(self, request: StructuredRequest) -> list[Any]:
        payloads: list[Any] = []
        schema = _strip_unsupported(request.json_schema)
        for i in range(request.n):
            response = self._client.messages.create(
                model=self._model,
                max_tokens=16000,
                system=request.system,
                output_config={"format": {"type": "json_schema", "schema": schema}},
                messages=[
                    {
                        "role": "user",
                        "content": request.prompt
                        if request.n == 1
                        else f"{request.prompt}\n\nThis is proposal {i + 1} of {request.n}; "
                        "it must differ materially from any earlier proposal.",
                    }
                ],
            )
            if response.stop_reason == "refusal":
                log.warning("LLM refused a %s request; recording as invalid attempt", request.task)
                payloads.append({"__refused__": True})
                continue
            text = next((b.text for b in response.content if b.type == "text"), "")
            try:
                payloads.append(json.loads(text))
            except json.JSONDecodeError:
                payloads.append({"__unparseable__": text[:200]})
        return payloads


class DeterministicStubBackend:
    """Offline, deterministic payload generator for sample runs and tests.

    Thesis payloads are a pure function of the discovery-data summary in
    ``request.context``; critique payloads are a pure function of the critiqued
    thesis's recorded results. No randomness, no network.
    """

    def complete(self, request: StructuredRequest) -> list[Any]:
        if request.task == "thesis_generation":
            return self._theses(request)
        if request.task == "critique":
            return [self._critique(request.context)]
        raise ValueError(f"unknown structured task {request.task!r}")

    def _theses(self, request: StructuredRequest) -> list[Any]:
        ctx = request.context
        instruments: list[dict] = ctx["instruments"]  # [{key, trend, vol, category}]
        docs: list[dict] = ctx.get("qualitative", [])
        critique = ctx.get("critique")
        exclude: set[str] = set(ctx.get("exclude_instruments", []))

        ranked = sorted(instruments, key=lambda i: (-abs(i["trend"]), i["key"]))
        candidates = [i for i in ranked if i["key"] not in exclude] or ranked

        payloads = []
        for inst in candidates[: request.n]:
            direction = "long" if inst["trend"] >= 0 else "short"
            if critique is not None and critique.get("flip_direction"):
                direction = "short" if direction == "long" else "long"
            doc_note = f" Qualitative context: {docs[0]['text'][:120]}" if docs else ""
            refined = (
                " Refined after critique: " + critique["suggested_direction"] if critique else ""
            )
            payloads.append(
                {
                    "rationale": (
                        f"Discovery-window data shows {inst['key']} with an average daily "
                        f"return of {inst['trend']:+.5f} (volatility {inst['vol']:.5f}), "
                        f"suggesting a persistent {direction} drift.{doc_note}{refined}"
                    ),
                    "hypothesis": {
                        "instruments": [inst["key"]],
                        "direction": direction,
                        "horizon": "refinement_window",
                        "condition": (
                            f"{inst['key']} continues the drift regime observed in the "
                            "discovery window"
                        ),
                        "testable_claim": (
                            f"Mean daily {direction} return of {inst['key']} is positive "
                            "and statistically distinguishable from zero."
                        ),
                    },
                }
            )
        return payloads

    def _critique(self, ctx: dict) -> dict:
        weaknesses = []
        screening = ctx.get("screening")
        backtest = ctx.get("backtest")
        hypothesis = ctx["hypothesis"]
        if screening and screening["verdict"] == "fail":
            weaknesses.append(
                f"Statistical evidence was insufficient: p-value {screening['p_value']:.4f} "
                f"exceeded the multiplicity-adjusted threshold "
                f"{screening['adjusted_threshold']:.4f} for instrument "
                f"{hypothesis['instruments'][0]}."
            )
        if backtest is not None and backtest["net_return"] <= ctx.get("underperform_bar", 0.0):
            weaknesses.append(
                f"Refinement backtest net return {backtest['net_return']:+.4f} "
                f"(gross {backtest['gross_return']:+.4f}) did not survive transaction "
                "costs, slippage, and financing for the hypothesized "
                f"{hypothesis['direction']} exposure."
            )
        if not weaknesses:
            weaknesses.append(
                f"The thesis on {hypothesis['instruments'][0]} relies on a drift estimate "
                "whose sign is unstable across the discovery window subsamples."
            )
        trend = ctx.get("instrument_trend", 0.0)
        wrong_way = (hypothesis["direction"] == "long" and trend < 0) or (
            hypothesis["direction"] == "short" and trend > 0
        )
        if wrong_way:
            suggestion = (
                f"Reverse the exposure: discovery data drift for "
                f"{hypothesis['instruments'][0]} is {trend:+.5f}, opposite to the "
                f"hypothesized {hypothesis['direction']} direction."
            )
        else:
            suggestion = (
                "Target an alternative instrument with a stronger discovery-window "
                "drift, keeping the same regime condition."
            )
        return {"weaknesses": weaknesses, "suggested_direction": suggestion}


def build_backend(backend: str, model: str, api_key_env: str) -> StructuredBackend:
    if backend == "deterministic_stub":
        return DeterministicStubBackend()
    if backend == "anthropic":
        return AnthropicStructuredBackend(model=model, api_key_env=api_key_env)
    raise ValueError(f"unknown LLM backend {backend!r}")
