# ADR-0001: Start as a modular monolith

## Status
Accepted

## Context
The project has multiple conceptual layers—catalog, search, ingestion, telemetry, and later operational reasoning—but only one initial product loop.

Premature service decomposition would increase deployment, coordination, testing, and agent-context cost without proving any product value.

## Decision
Use one repository and one deployable application boundary initially, with explicit internal modules and typed contracts.

External providers must be accessed through adapters.

## Consequences
Positive:
- simple local development
- simple deployment
- easier end-to-end testing
- low agent coordination cost
- boundaries can still be preserved in code

Negative:
- modules share one runtime
- later extraction may require work

## Revisit when
A module has independent scaling, security, deployment, or ownership needs that create measurable pain.
