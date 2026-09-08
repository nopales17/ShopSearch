# Test Strategy

- `unit/`: pure domain and ranking behavior
- `integration/`: catalog → search → telemetry boundaries
- `acceptance/`: user-visible vertical-slice behavior

Phase 1 should include a fixed retrieval evaluation set with human-authored expected relevance.

Issue #1 uses the standard-library unittest runner. `make test` runs 13 tests,
including real loopback HTTP journeys that follow rendered links, restart persistence,
foreign-session/invalid attribution rejection, fixture validation, explicit service
constraints and concurrent/idempotent event writes. Fixtures never assert real stock.

After installing requirements-dev.txt, `make check PYTHON=.venv/bin/python` also
compiles modules, checks Ruff lint/format and runs mypy on application/contracts.
The HTTP acceptance suite needs permission to bind temporary loopback ports.
These tests establish implementation behavior, not retrieval quality or market evidence.
