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

P1 presents a fictional specialty shop, FORM & FIELD, using 30 permitted real-object
photographs from the Cleveland Museum of Art's CC0 collection. These are museum
objects, not goods offered for sale or the prospective shop's inventory. The site
discloses manual curation and illustrative prices. Call/Directions are simulated.

Use Python 3.11/3.12. First setup installs the optional pinned CLIP runtime and
downloads model weights (several hundred MB; network required). Photos and their
precomputed vectors are already committed. Subsequent inference works locally.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
make pitch-setup PYTHON=.venv/bin/python
make pitch PYTHON=.venv/bin/python
```

Open `http://127.0.0.1:8000`. Follow “See What's In Store,” then try “small blue one
under $50,” “simple clear one,” or “colorful.” Price ceilings are deterministic;
unknown prices are excluded. CLIP ranks image similarity without an LLM. Startup
warms text inference. This remains a local demo, not a publicly hosted website.

Pitch events persist separately to `data/local/pitch-telemetry.jsonl` with
`pitch_demo` classification and store/session/search correlation. For another port/log:

```sh
.venv/bin/python -m apps.web.pitch_server --port 8018 --telemetry-path /tmp/pitch.jsonl
make pitch-eval PYTHON=.venv/bin/python
make check PYTHON=.venv/bin/python
```

The evaluator uses frozen pre-retrieval labels and writes a timestamped result under
`data/local/pitch-evaluations/`, preserving committed history. See `experiments/search_v0/PITCH_PROTOCOL.md`,
`docs/EVIDENCE.md` (E-001), and `data/pitch/README.md` for provenance and limitations.
The baseline passed its narrow pitch gate; vague queries are uneven, unrelated
queries still return neighbors, and manually tagged lexical search scored higher.

## Run the Issue #1 fixture slice

This local slice uses only explicitly marked demo/test fixtures. It is not Customer Zero inventory, does not show product photos, and uses deterministic token matching rather than semantic retrieval.

```sh
make run
```

Open `http://127.0.0.1:8000`. Events persist to `data/local/telemetry.jsonl`, which is ignored by Git. Use a separate file while testing if you want to keep runs apart:

```sh
python3 -m apps.web.server --telemetry-path /tmp/shopsearch-telemetry.jsonl
```

Requires Python 3.11+. The fixture mode has no third-party runtime dependencies. Install
development-only lint/type checkers once, then run the same checks as CI:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
make check PYTHON=.venv/bin/python
```

`make test` runs the standard-library unit and HTTP acceptance suite without extra
packages. `make check` adds compilation, Ruff lint/format checks and mypy. CI is
configured for Python 3.11 and 3.12; a local pass does not claim a remote CI run.

Only one process may write a telemetry file. Events persist across restart; tests
use temporary files. Search/item events include session/store/search IDs and catalog
snapshots; duplicate event IDs are rejected or ignored if identical. Page reloads
are new interactions, not deduplicated visits. No purchase or availability is inferred.

The HTTP server binds loopback only and is for local development, not public hosting.
The fixture loader deliberately rejects real catalogs. Placeholder ranking returns
up to 12 records even when token overlap is zero. Price/category constraints work at
the service boundary; natural-language price parsing and filter UI are in P1 pitch mode.
See `docs/adr/0002-local-fixture-runtime.md` for runtime/storage limits.
