# P1: fixed local pitch evaluation

This is a bounded retrieval experiment, authorized before the prospective Customer
Zero pitch. No customer adoption or willingness to pay is established.

Dataset: 30 manually selected CC0 photographs of museum glass objects; these stand
in for a generic collectible/homewares assortment. They are not merchandise for
sale, contemporary smoke-shop inventory, or observations at the prospective shop.
Illustrative USD prices exercise exact filters; they are not appraisals or quotes.

The selection and relevance file were written after visual contact-sheet review,
before image embedding generation or any text-to-image retrieval. Labels are agent
judgments, not independent human ground truth. The runtime must not load them or
the curated tags into ranking. Photo source titles and dimensions remain provenance.

Baseline: one unmodified CLIP ViT-B/32 image/text encoder, cosine similarity on
precomputed image embeddings. No LLM, fine-tuning, per-query rules or prompt tuning.
Price expressions are removed from visual text and enforced separately. Compare
with existing title/tag token overlap, explicitly identifying that baseline's
curation advantage. Do not change labels to accommodate failures.

Report top-five IDs, hit@3 on strong matches, precision@5, graded nDCG@5, exact price
violations and controls. Report cold initialization, first query, repeated warm
uncached query p50/p95, and cached timings separately. CPU/threads and Python/model
versions must be recorded. The acceptance target is in pitch_evaluation.json.

Budget: one baseline and at most one explicitly recorded correction for a diagnosed
technical fault, not post-hoc relevance retuning. If quality fails, preserve results
and identify a bounded next test. Out-of-assortment text may still return nearest
neighbors; no inventory/demand claim can be based on these counts.

Catalog effort: record agent-assisted elapsed sourcing/selection time separately
from retrieval/UI engineering. No merchant manual-effort estimate is inferred.
