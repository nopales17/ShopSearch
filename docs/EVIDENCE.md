# Evidence Log

This file records what experiments actually established.

Do not use it as a brainstorm list.
Do not rewrite old findings to fit later narratives.
Append new evidence entries.

## Entry template

### E-XXX — Short title
**Date:** YYYY-MM-DD

**Claim**

What the experiment supports.

**Scope**

Dataset, store, model, time window, or environment.

**Evidence**

- measured result
- measured result

**Weaknesses / alternative explanations**

- limitation
- limitation

**Does not establish**

- stronger claim that remains unsupported

**Next discriminating test**

The cheapest experiment likely to distinguish competing explanations.

---

No project evidence has been established yet.

### E-001 — P1 local CLIP photo-discovery baseline
**Date:** 2026-09-08 local; raw run 2026-09-09 05:09 UTC.

**Claim**
Unmodified CLIP can support a responsive local pitch with some visually relevant
results on this curated assortment. This is a narrow feasibility result, not
incremental customer value or superiority over manual tagged search.

**Scope**
30 CC0 Cleveland Museum of Art glass-object photos, manually selected as generic
specialty-retail stand-ins. No actual shop inventory or sales. Prices are illustrative.
CLIP ViT-B/32, pinned revision `3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268`;
Python 3.12.14, macOS ARM64, CPU with four threads. No tuning, LLM or caption ranking.
Selection and agent visual judgments were frozen before image embeddings or queries;
the rubric is not independent human ground truth.

**Evidence**
- Frozen gate: 8/10 tasks require a strong top-three match (or all price-only results
  valid), zero price violations and warm uncached p95 <1 second. Observed 10/10 pass,
  zero violations. Under-$1 returns none; strict/inclusive $50 and unknown-price
  behavior are separately checked in tests.
- Nine visual tasks: mean precision@5 **0.4889**, graded nDCG@5 **0.7328**.
  Tagged lexical comparison mean nDCG@5 **0.8883**; CLIP did not outperform it.
- “Small blue one” returns sapphire and aqua bowls first; “simple clear one” returns
  the clear straight glass first. “Colorful” and “dark and weird” each score only
  0.4 precision@5 and 0.3270 nDCG@5. An unrelated “running shoe” still returns objects.
- Initialization **3.031 s**; first query **565.46 ms**. Warm uncached n=100:
  p50 **9.80 ms**, p95 **12.27 ms**. Cached n=100: p50 **0.625 ms**, p95 **0.729 ms**.
  Offline image-index build including model load took **15.70 s**.
- Follow-up loopback HTTP n=30 against the warmed preview, including JSONL writes:
  p50 **2.96 ms**, p95 **33.89 ms**. Mixed initial/cached queries; excludes browser
  rendering and does not test sustained traffic or large logs.
- Approximate agent-assisted source selection/catalog preparation: **~10 minutes
  estimated**, including a timestamped ~5-minute preparation segment. Existing
  museum photos/metadata removed capture work. This is not measured merchant labor.

Artifacts: `experiments/search_v0/pitch_evaluation.json` (SHA-256
`63a487da1315b36db10ffab51d6de0d90bad6dfa2ad6b10fb87cb9c7bd936153`),
`pitch_results.json`, `pitch_http_results.json`, evaluator and `PITCH_PROTOCOL.md`;
source/effort notes in `data/pitch/README.md`. Catalog/index hashes bind the run.

**Weaknesses / alternative explanations**
The selection and labels share one agent curator; tags advantage the lexical
baseline. Ten queries and museum studio photos are a small, favorable sample.
Size/mood are ambiguous. Passing hit@3 can coexist with many poor top-five matches.
Local warm timings are not deployment or browser-latency guarantees. No relevance
threshold separates out-of-assortment requests. No independent user task comparison ran.

**Does not establish**
Customer adoption, willingness to pay, smoke-shop suitability, search-over-browse
benefit, stock truth, unmet demand, automated ingestion, catalog labor savings,
SER performance or cross-store/vertical transfer.

**Next discriminating test**
Use the truthful demo in the first owner conversation. With permission, capture a
small real-store assortment and independent owner/customer query judgments before
comparing image retrieval against tagged search and browsing. Measure full manual
capture/entry/review effort separately. Do not start automated shelf ingestion.
