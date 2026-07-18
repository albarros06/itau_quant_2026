# Contract: Thesis Generation Output Schema

Implements Constitution Principle III (Constrained LLM Autonomy) and FR-008–FR-011. This is the
**only** channel through which LLM output enters the system — structured, schema-validated, never
executed.

## JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "TradingThesisDraft",
  "type": "object",
  "required": ["rationale", "hypothesis"],
  "additionalProperties": false,
  "properties": {
    "rationale": {
      "type": "string",
      "minLength": 20,
      "description": "Plain-language justification grounded in current market conditions and qualitative context."
    },
    "hypothesis": {
      "type": "object",
      "required": ["instruments", "direction", "horizon", "condition", "testable_claim"],
      "additionalProperties": false,
      "properties": {
        "instruments": {
          "type": "array",
          "items": { "type": "string" },
          "minItems": 1,
          "description": "Instrument/tenor keys; MUST be within the configured universe."
        },
        "direction": { "type": "string", "enum": ["long", "short", "spread", "relative_value"] },
        "horizon": { "type": "string", "description": "Config-defined horizon bucket (e.g. tenor label)." },
        "condition": { "type": "string", "description": "The market/qualitative condition the thesis is contingent on." },
        "testable_claim": {
          "type": "string",
          "minLength": 10,
          "description": "The specific, falsifiable claim screening will test."
        }
      }
    }
  }
}
```

## Contract rules

1. **Two-stage validation**: the LLM call uses the provider's structured-output/tool-use mode
   constrained to this schema, AND the response is independently re-validated against the same
   schema (as a Pydantic model) before being persisted as a `TradingThesis`. Provider-side
   enforcement failing silently is not trusted as the sole guarantee (research.md §3).
2. **No repair on failure**: a response that fails validation is persisted with
   `status = invalid_schema` (data-model.md) and excluded from screening — never partially parsed,
   coerced, or defaulted into validity (FR-011).
3. **`instruments` universe check**: entries not present in the run's configured instrument
   universe cause validation failure with a specific reason (spec Edge Case: "Generation requests
   an instrument or market not in configuration").
4. **Inertness**: nothing in this schema, or in any code that consumes it, may resemble an
   executable instruction, order payload, or capital allocation — the schema is data-only by
   construction (Principle III, spec Out of Scope).
