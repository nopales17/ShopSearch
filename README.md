# ShopSearch

ShopSearch explores a simple product thesis:

> Make messy physical specialty-retail inventory intuitively searchable online without requiring the merchant to manually build and maintain a conventional ecommerce catalog.

The first proof is intentionally narrow:

1. Load a small manually curated catalog of real product images.
2. Search it with natural language such as `small blue one`.
3. Apply hard constraints such as `under $50`.
4. Show actual inventory images instantly.
5. Measure whether real users browse, search, click items, call, or request directions.

Production photo ingestion requires customer-value and labor/quality evidence. Bounded research and sales discovery may run alongside the trunk without changing production scope. Customer image uploads are deferred; the first search input is text.

## Start here
Read `AGENTS.md` first, then its prescribed order:
- `docs/CHARTER.md`
- `docs/STATUS.md`
- `docs/ARCHITECTURE.md`
- `docs/MAP.md`
- `docs/PRODUCT.md` before product implementation
- `docs/HYPOTHESES.md` for experiments, strategic context and promotion gates
- `docs/SLICES.md` before implementing a platform transition slice

## Repository principle
The project separates:
- what exists → `docs/MAP.md` + code
- what matters now → `docs/STATUS.md`
- what comes later → `docs/ROADMAP.md`
- why architecture is shaped this way → `docs/adr/`
- what experiments actually established → `docs/EVIDENCE.md`

The dated September 2026 white paper is summarized and qualified in `docs/HYPOTHESES.md`; it is not implementation state, evidence, or a scope override. The repository has an Issue #1 fixture slice and a generic photographic pitch demo. The prospective Customer Zero has not been formally pitched; payment/willingness to pay remain unvalidated.

Git remembers history. `STATUS.md` should stay current and short.

## Run the photographic pitch demo

P1 presents a fictional specialty shop, FORM & FIELD, using 90 permitted real-object
photographs (30 originally curated, 60 mechanically selected) from the Cleveland Museum
of Art's CC0 collection. These are museum objects, not goods offered for sale or the
prospective shop's inventory. The site
discloses manual curation and illustrative prices. Call/Directions are simulated.

Use Python 3.11/3.12. First setup installs the pinned WSGI runtime, the optional pinned
CLIP runtime, and model weights (several hundred MB; network required). Photos and their
precomputed vectors are already committed. Subsequent inference works locally.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
make pitch-setup PYTHON=.venv/bin/python
make serve PYTHON=.venv/bin/python
```

Open `http://127.0.0.1:8000`. Follow “See What's In Store,” then try “small blue one
under $50,” “simple clear one,” or “colorful.” Price ceilings are deterministic;
unknown prices are excluded. CLIP ranks image similarity without an LLM. Startup
warms text inference. The storefront is served by the Flask application in
`apps/web/wsgi.py` under Waitress, the production HTTP adapter selected in ADR-0004;
`make pitch` remains an alias. This remains a local demo, not a publicly hosted website.

Storefront events persist to the platform database (`data/local/shopsearch.sqlite3`) in
the store-scoped telemetry table, keeping the `pitch_demo` classification and
store/session/search correlation. For another port:

```sh
.venv/bin/python -m apps.web.wsgi --port 8018
make pitch-eval PYTHON=.venv/bin/python
make report PYTHON=.venv/bin/python
make check PYTHON=.venv/bin/python
```

`make report` reads the `pitch-demo` store's recorded events and prints counts with
explicit denominators, including `homepage_viewed` sessions, catalog opens, searches,
zero-result searches, normalized queries and item/action clicks; `--store-id` selects
another store, and `--telemetry-path` reads a legacy JSONL log. An older local log can
be migrated with `.venv/bin/python -m backend.telemetry.import_jsonl`. It is a read-only
local operator view: sessions are not people, clicks are not visits or purchases, demo
and merchant-self traffic are reported separately from live customer traffic, and counts
are not availability or customer-value evidence.

The evaluator uses frozen pre-retrieval labels and writes a timestamped result under
`data/local/pitch-evaluations/`, preserving committed history. See `experiments/search_v0/PITCH_PROTOCOL.md`,
`docs/EVIDENCE.md` (E-001), and `data/pitch/README.md` for provenance and limitations.
The baseline passed its narrow pitch gate; vague queries are uneven, unrelated
queries still return neighbors, and manually tagged lexical search scored higher.

## Merchant shell (local)

Founder-provisioned merchant accounts sign in at `/manage/login`; `/manage` lists the
store's items with their listing and index state and is read-only in this slice.

```sh
.venv/bin/python -m backend.auth.cli --store-id pitch-demo create --username alice
.venv/bin/python -m backend.auth.cli --store-id pitch-demo list
.venv/bin/python -m backend.auth.cli --store-id pitch-demo disable --username alice
.venv/bin/python -m backend.auth.cli --store-id pitch-demo reset --username alice
```

Passwords are entered at an interactive prompt and never as arguments. The merchant
cookie is `Secure`, so browsers accept it on a localhost origin over http while any other
host needs HTTPS. See `docs/CREDENTIALS.md` for session, CSRF and throttling details.

## Run the Issue #1 fixture slice

This local slice uses only explicitly marked demo/test fixtures. It is not Customer Zero inventory, does not show product photos, and uses deterministic token matching rather than semantic retrieval.

```sh
make run
```

Open `http://127.0.0.1:8000`. Events persist to `data/local/telemetry.jsonl`, which is ignored by Git. Use a separate file while testing if you want to keep runs apart:

```sh
python3 -m apps.web.server --telemetry-path /tmp/shopsearch-telemetry.jsonl
```

Requires Python 3.11+. The Issue #1 fixture slice itself has no third-party runtime
dependencies; the photographic storefront and full test suite use the pinned
Flask/Waitress runtime in `requirements.txt`. Install the development checks once, then
run the same checks as CI:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
make check PYTHON=.venv/bin/python
```

`make test` runs the unit and HTTP acceptance suite, including the WSGI storefront
adapter. `make check` adds compilation, Ruff lint/format checks and mypy. CI is configured
for Python 3.11 and 3.12; a local pass does not claim a remote CI run.

Only one process may write a telemetry file. Events persist across restart; tests
use temporary files. Search/item events include session/store/search IDs and catalog
snapshots; duplicate event IDs are rejected or ignored if identical. Page reloads
are new interactions, not deduplicated visits. No purchase or availability is inferred.

The HTTP server binds loopback only and is for local development, not public hosting.
The fixture loader deliberately rejects real catalogs. Placeholder ranking returns
up to 12 records even when token overlap is zero. Price/category constraints work at
the service boundary; natural-language price parsing and filter UI are in P1 pitch mode.
See `docs/adr/0002-local-fixture-runtime.md` for runtime/storage limits.
