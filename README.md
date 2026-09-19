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

## Run the platform (production runtime)

The production entry point is generic: it takes every path, store ID and binding from
`SHOPSEARCH_*` environment variables, opens the configured database and media root,
runs the forward-only migrations and serves only the listed stores. It never creates or
imports a store, and it fails closed when configuration is missing or invalid.

```sh
export SHOPSEARCH_DATABASE=/var/lib/shopsearch/shopsearch.sqlite3
export SHOPSEARCH_MEDIA_ROOT=/var/lib/shopsearch/media
export SHOPSEARCH_STORES=live-store          # explicit allowlist; no default store
export SHOPSEARCH_BIND_HOST=127.0.0.1        # loopback behind Caddy
export SHOPSEARCH_PORT=8000
make serve PYTHON=.venv/bin/python
```

`GET /health` checks the real database and media root (200 healthy, 503 with a generic
body on failure) before hostname resolution. Operational logs are JSON lines on the
standard logging stack, separate from telemetry. `deploy/` holds the provider-neutral
Caddy template, systemd units (including the nightly backup timer) and an environment
file example; `docs/OPERATIONS.md` documents directories, ownership, backup, restore and
the executed local restore drill. No hosting provider, domain, certificate or bucket is
configured or claimed.

Merchant accounts for a deployed store are founder-provisioned interactively; the service
has no committed secret and no Flask client-side session. The explicit interactive local
demo adds one plainly labeled `demo`/`demo` demonstration credential
(`apps/web/demo_runtime.py`) that generic startup never creates or reveals.

## Run the photographic pitch demo (explicit interactive developer path)

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
make demo PYTHON=.venv/bin/python
```

`make demo` prints everything it uses:

```
Form & Field storefront: http://127.0.0.1:8000/
Merchant sign-in: http://127.0.0.1:8000/manage/login
Local demonstration credential: demo / demo (local demo only; not a production account)
```

As a customer, open `http://127.0.0.1:8000`. Follow “See What's In Store,” then try
“small blue one under $50,” “simple clear one,” or “colorful.” Price ceilings are
deterministic; unknown prices are excluded. CLIP ranks image similarity without an LLM.
Startup warms text inference.

As the demo merchant, open `/manage/login` and sign in with `demo` / `demo`. That account
is created only by the explicit local demo command and is plainly a local demonstration
credential; it is not a production account, and the deployed runtime never provisions or
displays it. In the demo you can:

- take or upload one photo with an optional price, title and category, and use the
  “I just took this photo” capture attestation;
- see the new item in the storefront immediately — it is browsable, appears in category
  and price browsing, and is *not yet* searchable by description;
- press **Make searchable now** on the confirmation page or item page to run the existing
  indexer on demand, after which the item joins description search;
- edit title/category/price, hide/unhide, mark sold/relist and replace the photo.

The 90 committed museum objects stay read-only with their Cleveland Museum of Art / CC0
attribution: only items you upload into the local demo can be changed, and a direct
request against a museum object is refused server-side.

`make demo` (`python -m apps.web.demo`) is the only command that seeds the demo store,
imports its dataset and embeddings and provisions the demo credential; production startup
never does any of that. It runs from the dedicated, ignored demo runtime root
`data/local/form-and-field-demo/`, so it never touches your generic local platform state
in `data/local/shopsearch.sqlite3` and `data/local/media/`. **The demo keeps your local
state between starts:** stop it and run `make demo` again and your uploads and edits are
still there. To go back to the pristine 90-item baseline (this deletes the local demo
runtime, so stop the demo first):

```sh
make demo-reset PYTHON=.venv/bin/python
```

`make demo-reset` requires the demo not to be running, deletes only the dedicated
`form-and-field-demo` runtime directory, rebuilds the committed baseline plus the
`demo`/`demo` credential, verifies the counts and exits without starting the server.

Storefront events persist to that store's telemetry table, keeping the `pitch_demo`
classification for anonymous traffic and `merchant_self` for a signed-in demo merchant,
with store/session/search correlation. They are recorded demo interactions, not people,
demand or customer value. `make pitch` remains an alias, and this remains a local demo,
not a publicly hosted website. For another port:

```sh
.venv/bin/python -m apps.web.demo --port 8018
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
store's items with their listing and index state and publishes a new item from one photo
plus an optional price, title and category. New items are browsable immediately and
become searchable by description after the next indexer run
(`.venv/bin/python -m backend.search.indexer --store-id live-store`), or — inside the
interactive local demo only — through the **Make searchable now** action.

A live store's merchant accounts are provisioned by the founder, interactively, and are
unrelated to the local `demo` / `demo` demonstration account. The demo credential lives
only in the explicit demo composition: the store record, the environment configuration,
the deployment files and the founder CLI never create it, and a demo store stays
read-only in production composition even if an account exists for it.

```sh
.venv/bin/python -m backend.auth.cli --store-id live-store create --username alice
.venv/bin/python -m backend.auth.cli --store-id live-store list
.venv/bin/python -m backend.auth.cli --store-id live-store disable --username alice
.venv/bin/python -m backend.auth.cli --store-id live-store reset --username alice
```

Passwords are entered at an interactive prompt and never as arguments. The merchant
cookie is `Secure`, so browsers accept it on a localhost origin over http while any other
host needs HTTPS. See `docs/CREDENTIALS.md` for session, CSRF and throttling details.

## Operator commands

```sh
make backup PYTHON=.venv/bin/python    # consistent SQLite snapshot + media mirror + verify
make restore PYTHON=.venv/bin/python   # restore onto a clean destination (refuses to overwrite)
.venv/bin/python -m backend.search.indexer --store-id live-store   # process pending/failed items
```

Requires Python 3.11+. Install the development checks once, then run the same checks as
CI:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
make check PYTHON=.venv/bin/python
```

`make test` runs the unit and HTTP acceptance suite, including the WSGI storefront
adapter. `make check` adds compilation, Ruff lint/format checks and mypy. CI is configured
for Python 3.11 and 3.12; a local pass does not claim a remote CI run.

Events persist in the store-scoped platform database across restart; tests use temporary
directories. Search/item events include session/store/search IDs and catalog snapshots;
duplicate event IDs are rejected or ignored if identical. Page reloads are new
interactions, not deduplicated visits. No purchase or availability is inferred. The
HTTP server binds loopback and is intended to sit behind a TLS-terminating proxy, not to
be exposed directly. The Issue #1 fixture runtime is retired; see
`docs/adr/0002-local-fixture-runtime.md` (historical) and `docs/OPERATIONS.md`.
