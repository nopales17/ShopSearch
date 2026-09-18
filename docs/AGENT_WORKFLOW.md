# Agent Workflow

This document defines how human judgment and different AI agents cooperate on this
repository.

It defines **roles and handoffs**, not project state. `docs/STATUS.md` owns the current
objective and next trunk task. The project's other owning documents remain authoritative
for product, architecture and evidence.

## Operating model

The basic loop is:

Human / senior reasoning
→ decide what matters and define the task
→ repository records durable decisions
→ implementation worker executes
→ tests and self-audit
→ escalate unexpected or consequential findings
→ update repository truth
→ repeat

Do not use a stronger model merely because it is available. Do not use a cheaper model
to make a consequential decision merely because it can produce an answer.

## Implementation worker

Current default: **DeepSeek Flash through Codex**.

Use it aggressively for implementation once the objective and acceptance criteria are
clear.

Appropriate work includes code changes, tests, repository exploration, concrete bug
investigation, data plumbing, UI implementation, bounded refactors, experiment
execution, routine documentation updates and verification.

The worker may investigate assumptions before coding. It should prefer checking the
repository's actual contracts and behavior over guessing.

The worker is encouraged to consume enough context to work correctly. Cheap tokens are
not a reason to reduce verification.

The worker should stop and escalate when execution exposes a decision about product
scope, research meaning, architecture, prioritization, evidence semantics or another
high-impact ambiguity.

## Senior engineering and reasoning

Current default: **Sol**.

Use Sol when the difficult part is reasoning rather than typing code.

Typical uses include architecture, task decomposition, prioritization, difficult
debugging, large refactors, security-sensitive work, evaluating competing
implementations, and reviewing consequential changes.

Sol should usually produce a bounded decision, specification or review that can then be
handed back to the implementation worker.

Routine coding does not need to remain with Sol once the hard decision is resolved.

## Research and high-uncertainty reasoning

Current default: **Astra**.

Use Astra sparingly where deeper reasoning has unusually high leverage.

Typical uses include research direction, falsifiable hypothesis design, benchmark and
evaluator validity, interpreting ambiguous evidence, major conceptual forks and
decisions where a subtle mistake could invalidate substantial subsequent work.

For research repositories, Astra should help determine what an experiment can
legitimately establish. The implementation worker may then build and execute that
experiment.

Astra is not the default implementation model.

## Escalation principle

The important distinction is not task size. It is **where the uncertainty lives**.

A large but well-specified implementation can remain with the implementation worker.

A five-line change may deserve escalation if those five lines encode an architectural,
security, product or experimental decision.

Escalate when:

* the requested behavior conflicts with repository authority;
* an undocumented assumption materially affects correctness;
* architecture or public semantics must change;
* the agent cannot determine the correct acceptance criterion;
* experiment or evaluator semantics are ambiguous;
* evidence supports multiple materially different interpretations;
* repeated implementation attempts fail for reasons that appear conceptual rather than
  mechanical;
* proceeding would implicitly make a human-owned product, commercial or external
  decision.

## Handoff format

When escalating, preserve enough state that the senior model does not need to
reconstruct the entire failed attempt.

Include:

* current objective;
* relevant owning documents;
* exact decision or ambiguity;
* observed evidence;
* attempted approaches and results;
* current diff if one exists;
* constraints that must remain unchanged.

When handing work back to the implementation worker, provide:

* the selected approach;
* affected scope;
* acceptance criterion;
* explicit non-goals;
* any invariants discovered during reasoning.

## Repository memory

Durable project knowledge belongs in the repository, not only in an agent conversation.

Use:

* `STATUS.md` for current state and next trunk task;
* product documents for product requirements and release boundaries;
* architecture documents and ADRs for structural decisions;
* EVIDENCE for actual empirical findings and limitations;
* `AGENTS.md` for concise operating rules every coding session needs;
* this file for the multi-agent operating model.

Do not copy transient chat reasoning into project documentation merely because it
occurred. Record only conclusions, decisions, constraints or evidence that future work
actually needs.

## Fresh-session startup

A fresh coding agent should first read `AGENTS.md` and the repository's required
startup documents. From those it should determine the current objective and its role.

A fresh senior reasoning session should be given, or should read, at minimum:
`AGENTS.md`, this workflow document, `STATUS.md`, and the owning documents relevant to
the current question.

The goal is that changing agents does not change the project's facts, boundaries or
decision process.

