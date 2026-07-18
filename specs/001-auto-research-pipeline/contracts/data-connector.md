# Contract: Data Connector Interface

Implements Constitution Principle I (Provider-Agnostic Data Ingestion). Two connector families,
same shape, so provider-swapping works identically for numeric and qualitative data.

## MarketDataConnector

```text
Protocol MarketDataConnector:
    provider_id: str

    def fetch_series(category: DataCategory, instrument_key: str,
                      since: datetime | None) -> list[RawObservation]
        # Returns raw provider-native observations; does NOT clean or normalize.

    def health_check() -> ConnectorHealth
        # Used before a cycle starts to confirm the connector is reachable/authenticated.
```

## QualitativeContextConnector

```text
Protocol QualitativeContextConnector:
    provider_id: str

    def fetch_context(category: ContextCategory, since: datetime | None) -> list[RawContextDoc]
        # category ∈ {news, hydrology_outlook, macro_regime, ...} (config-defined)

    def health_check() -> ConnectorHealth
```

## Contract rules

1. **No downstream code may import a concrete provider class.** All access is through the
   `MarketDataConnector` / `QualitativeContextConnector` protocol, resolved at runtime by a
   provider registry keyed by configuration (`provider_id` → implementation), per FR-002.
2. **Provider-specific quirks stay inside the connector.** Authentication, pagination, field
   naming/units, and pagination cursors MUST be resolved before `fetch_series`/`fetch_context`
   returns — callers receive already-normalized shapes (`RawObservation`, `RawContextDoc`).
3. **Connectors do not clean data.** `cleaning` is a separate layer; a connector's job ends at
   "raw but normalized-shape" data.
4. **Swapping test**: replacing the registered implementation for a `provider_id` with a different
   one, with no changes to `cleaning`/`datastore`/anything downstream, is the acceptance test for
   this contract (spec Acceptance Scenario US2.2, SC-010).
