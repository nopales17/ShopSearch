# P2 bounded expanded-catalog comparison

Preregistered before expanded image-index construction or retrieval results, 2026-09-09.
One unchanged CLIP model, existing lexical title/tag substring-overlap comparator,
and exactly one hybrid: **0.70 × min-max CLIP + 0.30 × min-max lexical**. Normalize
per query over price-eligible items; a constant component becomes zero. Ties use
item ID. No tuning, independent model or production hybrid promotion in this pass.

Keep P1 judgments/results unchanged. Report two scopes separately:
1. Original P1 visual queries evaluated over original 30 IDs only, with original
   judgments. This subset replay is not an expanded-catalog quality claim.
2. Expanded 90-item evaluation: freeze a separate file before embedding, using the
   original visual queries and original 30 grades; new-item grades mechanically
   derived from source title/technique keyword proxies. Unmatched new items receive
   zero **proxy** grade, not a verified human judgment of irrelevance. Record the
   rules and all grades. This economical proxy benchmark is incomplete and favors
   lexical metadata; it cannot justify promotion or independent visual-quality claims.

Report nDCG@5, precision@5, strong hit@3, price violations and per-query results for
all three rankings. Composition checks: most expensive blue one, cheapest clear one,
colorful under $50, most expensive floral one, cheapest blue one under $50, blue one
over $25, between $25 and $50, and most expensive one. Semantic price sorts first
take 12 closest eligible matches, then order known prices, item ID breaking ties;
price-only sorts consider all eligible items. This fixed candidate window is not
a relevance rejection threshold. Evaluate exactly once; preserve weaknesses.

Dataset expansion uses CC0 Glass records, existing title filter and category round
robin, preserving the original 30. Metadata supplies titles/tags and deterministic
illustrative prices. Review one small contact-sheet sample, not 60 individual objects.
No merchant labor savings, smoke-shop suitability or customer evidence is inferred.
