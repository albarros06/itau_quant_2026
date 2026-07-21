# Contract: Declarative Connector & Config-Only Onboarding

Implements FR-016–FR-018 and extends 001's [data-connector.md](../../001-auto-research-pipeline/contracts/data-connector.md)
contract — the declarative connector satisfies that same `MarketDataConnector`/
`QualitativeContextConnector` protocol; this contract only specifies how it derives its behavior
from configuration instead of from a purpose-written Python module.

## Data Source Descriptor (input)

```text
provider_id: str
connector_kind: "declarative"
credential:                    # OPTIONAL: omit entirely for public open-data endpoints —
  env_var_name: str            # resolved at call time; never logged (FR-001)
  purpose: "market_data" | "qualitative_context"
base_url: str
endpoints:
  - category: str               # e.g. "spot", "news" — must be one of the config-defined categories
    path_template: str          # e.g. "/v1/series/{instrument_key}" or "/v1/news"
    method: "GET" | "POST"
    field_mapping:               # canonical field -> JMESPath, evaluated per response element
      instrument_key: str        # market data only
      category: str
      ts: str
      value: str                 # market data only
      source: str                 # context docs only
      text: str                   # context docs only
      provenance: str
    results_path: str | None      # optional JMESPath into the raw response locating the elements
                                   # array, for envelopes that are neither a bare array nor
                                   # {"data": [...]} (e.g. "records", "result.records"). Elements
                                   # need not be objects — a positional JMESPath index (e.g. "[3]")
                                   # is valid when a vendor's rows are arrays, not keyed objects.
    ts_format: str | None         # optional strptime pattern (e.g. "%d/%m/%Y") for vendors whose
                                   # timestamp string is not ISO-8601. Omit for ISO-8601 timestamps.
    response_format: "json" | "csv"  # default "json". "csv" parses the body as delimited text;
                                   # each row becomes a dict keyed by the header row, so the same
                                   # JMESPath field_mapping applies (for open-data portals that
                                   # publish plain CSV with no JSON API, e.g. ONS's S3 datasets).
    csv_delimiter: str             # default ";" (the Brazilian open-data convention)
    csv_encoding: str              # default "utf-8" (set "latin-1" for ISO-8859-1 vendors)
    row_filter: str | None         # optional JMESPath predicate per element; only truthy elements
                                   # are kept (e.g. "nom_subsistema == 'SUDESTE'" for files that
                                   # interleave many regions in one response)
    aggregate: "daily_mean" | None # optional: collapse sub-daily observations to one per calendar
                                   # day (the mean, stamped midnight UTC) — e.g. ONS's semi-hourly
                                   # CMO -> the standard daily-average figure. Market data only.
pagination:
  mode: "none" | "offset" | "cursor"
  # mode="offset": limit_param, offset_param
  # mode="cursor": cursor_param, next_cursor_path (JMESPath into the response for the next cursor)
```

## Behavior

1. **Auth**: the connector reads `credential.env_var_name` from the process environment at call
   time and attaches it as an `Authorization: Bearer <value>` header (the only auth scheme this
   contract supports — see Limitations). A missing/empty env var raises a visible
   `CredentialError` naming the vendor and env-var name; it is never silently treated as "no
   auth" (FR-001, Edge Case). A descriptor may omit the `credential` block entirely for public
   open-data endpoints — then NO Authorization header is sent (some hosts, e.g. plain S3, reject
   a stray Bearer header). Omission is an explicit authoring decision, not a fallback: a
   credential that IS configured but fails to resolve still raises.
2. **Fetch**: for `fetch_series(category, instrument_key, since)` /
   `fetch_context(category, since)`, the connector renders `path_template` with the supplied
   parameters, issues the request via `httpx`, locates the elements array within the raw response
   (a bare array, the `data` key, or — if the endpoint sets `results_path` — whatever that
   JMESPath expression finds), and evaluates each `field_mapping` entry with
   `jmespath.search(expression, response_element)` for every element the response's pagination
   yields, producing `RawObservation`/`RawContextDoc` instances exactly as 001's
   `data-connector.md` requires — normalized shape, no further caller-side interpretation needed.
   `ts` is parsed via `datetime.fromisoformat`, or via `endpoint.ts_format` (a `strptime` pattern)
   when the vendor's timestamp string is not ISO-8601.
3. **Provenance**: `provenance` is always read from the descriptor's mapping (per-element or a
   fixed literal in the descriptor), never inferred — matching 001's connector contract rule that
   provenance is declared, not guessed.
4. **Pagination**: `offset`/`cursor` modes loop until the response yields zero new elements or (for
   `cursor`) `next_cursor_path` evaluates to null/absent; `none` issues exactly one request.
5. **Health check**: `health_check()` issues a single request against the first configured
   endpoint and reports `ConnectorHealth(ok, detail)` — used identically to every other 001
   connector before a cycle starts.
6. **Discovery**: `discover()` (research.md §5) issues one request per configured endpoint (or a
   dedicated discovery endpoint if the descriptor is being *drafted*, not yet finalized) and
   returns whatever category/field metadata the response exposes, for the LLM interpretation step
   to turn into a proposal — it does not itself decide what the vendor "should" offer.

## Onboarding-drafting rules (FR-017/018)

1. The agent (`ops_agent.onboarding.draft`) inspects a vendor's interface description (API docs
   excerpt, sample response, or a live discovery probe) and asks the LLM, through 001's existing
   structured-output adapter, to emit **either** a schema-validated `DataSourceDescriptor` **or**
   an `OnboardingLimitation` — never a partial descriptor with guessed fields.
2. **When to emit `OnboardingLimitation` instead of a descriptor** — any vendor interface that
   needs:
   - an auth scheme other than a single bearer/API-key header (e.g., OAuth handshake, mutual TLS,
     signed-request HMAC),
   - pagination beyond simple offset or single-cursor-field cursor,
   - a response shape no combination of `results_path`/JMESPath `field_mapping`/`ts_format` can
     flatten into one element per canonical field (e.g., cross-referencing two separate endpoints
     per record, or a timestamp split across multiple fields with no single field a `ts_format`
     pattern can parse),
   - a non-HTTP transport (FTP, message queue, file drop outside the existing dropzone pattern).
   The agent reports `reason` and `unsupported_aspect` (data-model.md) rather than emitting a
   descriptor that would silently fail or misparse at ingestion time (FR-018).
3. A drafted `DataSourceDescriptor` is submitted as a `kind="onboarding"` `ProvisioningProposal`
   (proposal-lifecycle.md) touching `config/providers.yaml` — approval and effect follow the same
   path as any other proposal; no separate onboarding-approval mechanism exists.

## Swapping/independence test (inherited from 001)

Once approved, a `declarative` provider entry's series flow through `cleaning`/`datastore`
identically to a `python_module` provider entry — no code downstream of `ingestion/registry.py`
can tell the difference, satisfying both this contract and 001's existing "swapping test."
