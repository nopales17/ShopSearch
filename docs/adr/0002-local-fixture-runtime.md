# ADR-0002: Standard-library local fixture runtime

## Status
**Historical.** Accepted for Issue #1 on 2026-09-08; superseded for runtime by
ADR-0004 (Flask/Waitress, SQLite, content-addressed media) and retired in S10. It is
kept as the record of the Issue #1 fixture slice, not as a description of the shipped
runtime. No public deployment decision is implied then or now.

Retired in S10: `apps/web/server.py`, the fixture catalog loader
(`backend/catalog/repository.py`), the placeholder search fixture
(`backend/search/placeholder.py`) and the JSONL runtime store
(`backend/telemetry/jsonl_store.py`) were removed once the platform storefront passed
equivalent journeys (`tests/acceptance/test_pitch.py`, `test_wsgi_adapter.py`,
`test_catalog_media.py`, `test_platform_runtime.py`,
`test_backup_restore.py`). The committed `data/demo/` fixture records remain as Issue #1
history; no shipping code loads them. The one-way JSONL→platform importer
(`backend/telemetry/import_jsonl.py`) is retained for the documented historical-log
import use case and does not require the retired runtime.

## Context
The first caller needs a working browser → catalog → placeholder search → telemetry
loop. It does not need semantic retrieval, a frontend build system, or an owner backend.

## Decision
Use Python 3.11+ in one process with server-rendered HTML and CSS. The local HTTP
adapter composes catalog validation, typed placeholder retrieval and JSONL telemetry.
Keep domain contracts independent of HTTP. No third-party runtime packages are required.
Ruff and mypy are pinned development-only tools; unittest drives actual loopback HTTP tests.

Persist local fixture events as append-only JSONL with a process-local writer lock,
validation, event-ID duplicate detection, and flush/fsync before acknowledging writes.
Search attribution is checked against persisted session/store/catalog/result context.
One process must own each log file. Snapshots and a content-derived catalog version
preserve what was shown; they do not imply current physical availability.

Inline manual fixture provenance records materialize as separate ItemObservation
objects. EvidenceRef.source_id resolves to that observation ID in this fixture loader.
Their timestamps are explicitly synthetic source-record times, not real photo captures.
No AvailabilityState is inferred or published from them.

## Consequences and revisit
This keeps ADR-0001's modular monolith and gives later callers concrete boundaries.
The standard-library HTTP server is loopback-only local infrastructure, not a hardened
public server. Public deployment needs a production HTTP adapter and persistent storage
configuration; that can retain the same internal modules and one deployment boundary.
JSONL append scans are linear and search/result writes are separate; crash recovery,
multi-process writes and large-volume analytics are not provided. An incomplete search
trace after failure must not be treated as a completed zero-result search.
Revisit storage (e.g. SQLite) when a production reporting or deployment caller needs it.
