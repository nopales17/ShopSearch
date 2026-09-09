# P1 photographic demo dataset

30 manually selected photographs of real glass objects from the Cleveland Museum of
Art Open Access collection. These are museum collection objects, not sale inventory,
and have no relationship to the prospective Customer Zero. Prices are illustrative
test values, not quotes or valuations; one is unknown and one exactly $50 tests ceilings.

Each source API record declared CC0. Original web JPEG bytes are retained unchanged
(6,628,607 bytes total). `catalog.json` records accession/source/image URLs, license,
image SHA-256 and source-review time. Capture dates remain null. A review timestamp
does not mean the object was recently photographed or available. Public credits are
also available at `/credits`.

- Policy: https://www.clevelandart.org/open-access
- Source: https://openaccess-api.clevelandart.org/api/artworks/?q=glass&has_image=1&cc0=1&limit=100
- Additional blue candidates: https://openaccess-api.clevelandart.org/api/artworks/?q=blue&has_image=1&cc0=1&type=Glass&limit=100

`selection.json` contains manually chosen titles, illustrative prices and descriptive
tags. CLIP ranking uses image vectors, not these tags. Tags are used only by the
experiment's lexical comparator. `image_index.json` contains normalized CLIP vectors,
pinned model/revision and catalog/evaluation hashes.

Normal setup uses the committed dataset/index. For a deliberate dataset revision,
`tools/prepare_pitch_photos.py --source PATH_TO_API_JSON` prepares candidates and
contact sheets in ignored `data/local/`; `--publish` publishes the manual selection.
Publishing changes source-review timestamps and catalog version: inspect the output,
freeze a new evaluation version as appropriate, then run
`python -m tools.build_pitch_index`. Never silently reuse a stale index or rewrite
the historical P1 judgments/results to suit new images.

Preparation was agent-assisted, using existing online photos and metadata. Roughly
10 minutes is an estimate for sourcing/selection/catalog preparation, including about
5 minutes of timestamped preparation from 04:59:48 to 05:04:36 UTC on 2026-09-09.
It excludes capture, merchant review, ongoing refresh and software/model setup, and
is not a measured human catalog-labor baseline. Measure those separately on real
store merchandise before making any catalog-tax savings claim.
