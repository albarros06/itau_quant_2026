# Contract: Critique Generation Output Schema

Implements FR-020/FR-021 under the same constrained-autonomy rules as thesis generation
(Principle III) — structured, schema-validated, never free-form.

## JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ThesisCritique",
  "type": "object",
  "required": ["weaknesses", "suggested_direction"],
  "additionalProperties": false,
  "properties": {
    "weaknesses": {
      "type": "array",
      "items": { "type": "string", "minLength": 10 },
      "minItems": 1,
      "description": "Specific, concrete weaknesses — not generic restatements of failure."
    },
    "suggested_direction": {
      "type": "string",
      "minLength": 10,
      "description": "Concrete guidance for the next generation call in this lineage."
    }
  }
}
```

## Contract rules

1. Same two-stage validation and no-repair-on-failure rules as
   [thesis-schema.md](./thesis-schema.md).
2. A critique is always attached to exactly one `TradingThesis` (the one being critiqued) and is
   consumed as input context by the next `generation` call for that lineage — passed through
   `orchestration`, never called directly by `generation` reaching into `critique` (independence
   contract, [architecture-boundaries.md](./architecture-boundaries.md)).
3. `weaknesses` entries generic enough to apply to any thesis (e.g., "needs more data") fail
   validation's `minLength`/specificity intent and should be rejected by the calling layer's
   post-check, consistent with FR-020's "identifying specific weaknesses."
