# Web App

The storefront is server-rendered HTML/CSS served by `wsgi.py`: a Flask application under
Waitress, the production HTTP adapter selected in ADR-0004. No JavaScript framework or
frontend build step is needed. Do not put domain truth or retrieval logic in UI
components.

Modules:

- `wsgi.py` — production adapter. `main()` reads `SHOPSEARCH_*` configuration, serves only
  the configured stores and never provisions one.
- `storefront.py` — `open_platform_stack()` (no provisioning) and `open_demo_stack()`
  (explicit Form & Field provisioning), plus the storefront application.
- `demo.py` — the explicit interactive local demo command behind `make demo`.
- `demo_runtime.py` — the dedicated disposable demo runtime: bootstrap, local
  `demo`/`demo` credential, verified `make demo-reset`.
- `manage.py`, `manage_views.py` — merchant sign-in and the `/manage` catalog operations.
- `pitch_views.py`, `static/` — customer storefront copy, layout and behavior.
- `pitch_server.py` — the superseded S1 standard-library adapter, retained for the
  byte-parity test only.

Run instructions, the demo journey and the credential rules live in the root `README.md`,
`docs/OPERATIONS.md` and `docs/CREDENTIALS.md`; this file exists to orient changes, not to
duplicate them.
