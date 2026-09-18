# Agent Operating Rules

Mission: build the smallest reliable system that turns recently observed physical
specialty-retail inventory into intuitive, searchable customer discovery with minimal
merchant cataloging labor. This file is the operating summary; linked documents own
the details.

## Read before changing

Read in order:

1. `docs/CHARTER.md`
2. `docs/STATUS.md`
3. `docs/ARCHITECTURE.md`
4. `docs/MAP.md`

Then read only what the task needs:

- `docs/PRODUCT.md` before product, UI, public-copy or release work.
- `docs/HYPOTHESES.md` before experiments, strategic interpretation or promotion gates.
- `docs/ROADMAP.md` only when selecting future work.
- Relevant `docs/adr/` records before an architectural change.
- `docs/EVIDENCE.md` before citing or updating findings; never rewrite historical
  entries to make results look better.

Authority: PRODUCT is the release specification; STATUS plus code/tests describe
current state; ARCHITECTURE and ADRs define boundaries; EVIDENCE records what was
actually established. The dated white paper is strategic context, not implementation
state, measured evidence or permission to expand scope.

## Objective and scope

Current objective: deploy the conditional prospective Customer Zero website with an
honestly represented, manually curated real-item catalog, natural-language retrieval,
deterministic hard constraints and validated discovery telemetry. STATUS owns the
exact current objective and the single next trunk task; read it rather than relying on
this summary.

Keep one production-active objective. Sales/customer discovery may continue. Bounded
research may run in `experiments/` with a stated question, dataset, budget, artifact,
metric and stop/promotion criterion, but research must not mutate production
contracts, modules, dependencies or scope. Only the trunk promotes an implementation
after the relevant gates and an explicit STATUS decision. Do not start unrelated
features, skip roadmap phases silently or treat research success as production
authorization. The founder owns external owner contact and commercial outcomes;
agents must not invent them.

## Evidence, claims and telemetry

Distinguish observation, inference, decision and outcome. A search, click, direction
request, call, visual detection and purchase are not equivalent evidence. Preserve
provenance, permission, scope, timestamps and freshness; never silently convert
uncertainty into certainty. Model/LLM outputs are proposals or observations, not
authoritative truth.

Telemetry counts interactions, not people. Sessions are not unique people; clicks are
not visits, calls or purchases; zero results may reflect query, filter, coverage or
retrieval failure, not physical absence; a nearest-neighbor result is not proof of
suitability or availability. Keep test/demo traffic separate, validate event payloads
at boundaries, correlate search/item/action context and prevent duplicate counts.
Internal reports are read-only operator views, not demand or customer-value evidence.
Before public telemetry, resolve retention, access and applicable notice decisions. Do
not add indefinite raw-query retention for hypothetical future use.

Do not claim customer value, demand, adoption, willingness to pay, availability or
retrieval superiority from demo data, fixtures or unvalidated experiments. Use the
availability wording allowed by PRODUCT and ARCHITECTURE; "recently photographed" is
not "in stock".

## Small scoped changes

Before coding, state the current objective, affected modules, acceptance criterion and
what is intentionally not changing. Make the smallest change that satisfies the
acceptance criterion, with at least one immediate real caller. Keep modules narrow,
domain logic UI-independent and hard constraints deterministic. Prefer typed
contracts. Add a dependency only for a concrete reason. Do not refactor unrelated code
or turn a local fix into a framework, generic utility, agent manager or service
boundary.

## Testing and completion

Run `make check PYTHON=.venv/bin/python` (or the repository's documented equivalent)
before finishing. It compiles, checks Ruff lint/format, runs mypy and executes the
unittest suite; CI targets Python 3.11 and 3.12. Add focused unit and acceptance tests
for changed behavior and boundaries. HTTP acceptance tests bind loopback ports and may
need permission outside the sandbox. A local pass is not a remote-CI run.

A task is complete only when the acceptance test passes, the vertical slice still
works, project state is updated and the next agent can understand the change.

## Documentation updates

- `docs/STATUS.md`: update when product or implementation state changes; keep it
  current and concise.
- `docs/MAP.md`: update only when files, structure or responsibilities move.
- ADR: add or amend only when an architectural decision, boundary or invariant
  changes, not for routine implementation.
- `docs/EVIDENCE.md`: add only when an executed experiment established something.
  Append findings and limitations; preserve historical entries.
- `docs/GITHUB_ISSUES.md`: historical bootstrap definitions only; do not append new
  work there.
- `README.md`, `PRODUCT.md`, `CHARTER.md`, `ROADMAP.md`, `HYPOTHESES.md`: edit only
  when their owned content changes; do not duplicate them here.

## Do not silently change

- Product scope, release boundary, roadmap phase or commercialization claims.
- Architecture boundaries, ADRs or the one-active-objective rule.
- Core semantics: observation vs inferred identity vs availability vs public claim;
  search relevance vs inventory truth; strict/inclusive/unknown price behavior;
  provenance and freshness.
- Fixture, demo and Customer Zero labels; licensing or permission records; prices,
  timestamps or observation wording; generated or substitute imagery presented as real.
- Telemetry classification, retention or customer-facing claim semantics.
- Deployment, hosting, public-release prerequisites or external communication.

If a change needs any of these, stop, surface the decision and record it explicitly.

## Agent roles and escalation

This repository may be worked on by models with different roles. Do not assume every
agent should make every kind of decision.

### Implementation worker

The default implementation worker is currently DeepSeek Flash through Codex.

Its job is to:

* read the required repository context before changing code;
* execute clearly scoped implementation tasks;
* write and run tests;
* investigate concrete code-level questions and invariants;
* make small, local implementation decisions consistent with existing architecture;
* update owning documentation when the implemented state actually changes;
* report uncertainty, surprising findings and blocked dependencies.

The implementation worker should optimize for correctness and verification, not token
economy. It may read broadly when necessary.

It must **not independently decide** major product direction, research direction,
roadmap priority, architecture changes, evidence interpretation, benchmark semantics,
commercial strategy or external actions merely because it can implement something.

When one of those decisions becomes necessary, stop before making the consequential
change and surface:

1. the decision that is required;
2. the relevant facts and constraints;
3. viable options if clear;
4. what work is blocked pending the decision.

### Senior reasoning / engineering

The default senior reasoning model is currently Sol.

Escalate to this role for:

* architecture or cross-cutting design decisions;
* difficult or repeated debugging failures;
* substantial refactors;
* ambiguous product or implementation priorities;
* security-sensitive or high-impact changes;
* review of consequential implementation;
* situations where the implementation worker has made multiple unsuccessful attempts;
* decisions whose cost of being subtly wrong is substantially larger than the cost of
  additional reasoning.

Sol may define or refine the implementation task and hand bounded execution back to
the implementation worker.

### Research / high-uncertainty reasoning

The highest-level research reasoning model is currently Astra.

Reserve this role for:

* research question and experiment design;
* benchmark or evaluator validity;
* deciding what evidence would support or falsify a claim;
* interpreting ambiguous experimental results;
* major architectural or conceptual forks;
* questions where a plausible but incorrect answer could redirect substantial work.

Astra should generally decide or critique; routine implementation should return to the
implementation worker once the decision is clear.

### Human authority

The founder/user owns:

* final prioritization and tradeoffs;
* external customer or owner communication;
* permissions and commitments;
* commercial terms;
* acceptance of major product or research direction.

Agents may prepare information and options but must not invent external outcomes or
silently make these decisions.

### Default routing rule

If the task is already well specified and the remaining work is primarily execution,
use the implementation worker.

If deciding **what should be built, changed, measured or concluded** is the hard part,
escalate before implementation.

Repository documents remain authoritative for project facts. Agent role does not grant
permission to override STATUS, PRODUCT, architecture decisions, evidence rules or the
human-owned decisions above.

