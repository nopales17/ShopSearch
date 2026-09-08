# ADR-0002: Standard-library local fixture runtime

## Status
Accepted for Issue #1, 2026-09-08. No public deployment decision is implied.

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
