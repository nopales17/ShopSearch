# ADR-0003: Local precomputed CLIP retrieval for P1

## Status
Accepted 2026-09-08 for the explicitly authorized generic pitch milestone.

## Decision
Preserve ADR-0001's modular monolith and ADR-0002's HTTP/catalog/telemetry boundaries.
Add an optional pinned PyTorch/Transformers CLIP adapter, one precomputed image index
and an in-process cosine ranker. The concrete search protocol now serves fixture and
pitch callers. Image encoding runs offline; text encoding runs locally on CPU, warmed
at startup, with a bounded query cache. No LLM, vector database or hosted inference
service is needed for 30 images. The model revision, dataset hash and frozen evaluation
hash are recorded in the index. Dependencies have this immediate retrieval caller.

Hard price/category constraints run deterministically; unknown prices fail price
ceilings. Ranking does not infer identity, observation time, availability or public
claims. The catalog owns presentation snapshots. Manual source-review observations
resolve provenance but are not photo-capture or stock observations.

P1 has its own validated demo catalog and traffic classification. The CC0 museum
photographs are permitted real-object stand-ins, not goods for sale; assigned prices
are explicitly illustrative. This is an exception confined to demo data, not permission
to invent prices or observations in a store catalog. Source URLs, license declarations
and image hashes travel with records. Customer-facing disclosures preserve that scope.

## Consequences and revisit
First setup downloads substantial model weights; subsequent inference is offline.
Committed photos/vectors make the curated dataset reproducible without running ingestion.
The fixture command and dependency-light CI still work without model packages. HTTP
tests use a stub encoder; actual model quality is a separate frozen experiment.
Local JSONL and loopback-server limits remain. Production hosting, real store evaluation
and any storage replacement require their own concrete caller. Nearest neighbors always
exist unless filters remove every item; similarity is not a suitability guarantee.
The baseline passed a narrow pitch gate but did not beat manually tagged lexical search.
No vision ingestion, customer image search, SER or broader architecture is promoted.
