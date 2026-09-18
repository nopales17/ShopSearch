# Test Strategy

- `unit/`: pure domain and ranking behavior
- `integration/`: catalog → search → telemetry boundaries
- `acceptance/`: user-visible vertical-slice behavior
- `support/`: shared fixtures used by tests, never collected as tests themselves

Phase 1 should include a fixed retrieval evaluation set with human-authored expected relevance.

Issue #1 and P1 use the standard-library unittest runner. `make test` runs the full
suite, including real loopback HTTP journeys under the Flask/Waitress storefront
adapter, link/rendered-page checks, restart persistence, foreign-session/invalid
attribution rejection, fixture validation, explicit service constraints,
concurrent/idempotent event writes and the read-only demo funnel report. Fixtures never
assert real stock.

After installing requirements-dev.txt, `make check PYTHON=.venv/bin/python` also
compiles modules, checks Ruff lint/format and runs mypy on application/contracts.
The HTTP acceptance suite needs permission to bind temporary loopback ports.
These tests establish implementation behavior, not retrieval quality or market evidence.

P1 adds permitted-photo/hash/index validation, strict/inclusive/unknown price checks
and real HTTP photo/search/detail/simulated-action journeys. HTTP tests inject a stub
encoder so CI does not download a model. S1 adds storefront route, response-header,
session-cookie and legacy-vs-WSGI byte-parity checks. `make pitch-eval` runs actual
pinned CLIP against the frozen relevance judgments separately; see E-001 and
PITCH_PROTOCOL.

S9 adds the adversarial two-store isolation proof. `tests/support/isolation_fixture.py`
provisions the committed synthetic document `data/stores/isolation-fixture.json` twice
(`isolation-alpha`, `isolation-beta`) with distinct hostnames, branding, catalogs, media,
embeddings, merchants and telemetry, plus a registered-but-unprovisioned hostname. The
fixture deliberately reuses item IDs, source image bytes and the merchant username across
the two stores, so isolation must come from `StoreScope`; it is generated test data, not
Cloud City, not a prospective Customer Zero store and not evidence about a merchant or
customer. `tests/acceptance/test_store_isolation.py` is the concentrated suite: one
application process serves both hostnames (including over real loopback with two Host
headers), and catalog, detail, media, the frozen query set, generation/vector-cache
independence, merchant cookies/CSRF, telemetry and every S7/S8 mutation are crossed on
purpose and must fail closed. `tests/unit/test_schema_isolation.py` enumerates every table
in the schema, records its isolation mechanism and proves with direct inserts that SQLite
rejects cross-store child rows, unknown-store rows and a hostname claimed by two stores.
`tests/unit/test_store_registry.py` keeps the persistence import boundary: `sqlite3` and
the raw connection factory stay inside the repository layer. Tests may open raw
connections for these schema-level checks; application code may not.
