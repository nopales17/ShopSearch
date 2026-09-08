# Current Status

## Phase
Phase 1 — customer search proof.

## Last known good
Repository bootstrap only.

## Current objective
Ship one end-to-end vertical slice:

manual demo catalog → semantic search → hard filters → customer UI → telemetry.

## Active acceptance criteria
A local demo must:
1. load at least 30 manually curated product records,
2. accept free-text search,
3. return ranked visual results,
4. support at least one hard filter (`price_max`),
5. log `search_submitted`, `search_results_returned`, and `item_opened`,
6. pass a small fixed retrieval evaluation set,
7. avoid making unsupported real-time availability claims.

## Current task
Issue #1: bootstrap the runnable vertical slice and demo catalog contract.

## Blockers
None.

## Explicitly deferred
- shelf-photo object detection
- persistent item reconciliation across days
- POS / invoice ingestion
- owner recommendations
- multi-store logic
- generative product imagery

## Next
1. demo catalog
2. semantic retrieval baseline
3. customer search UI
4. telemetry
5. retrieval evaluation
6. deploy first real demo
