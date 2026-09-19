# Merchant credential handling (S6)

Operator notes for the founder-provisioned merchant accounts. Authentication is
store-scoped: usernames are unique inside one store, may repeat across stores, and a
session is only valid on its own store's resolved hostname.

## Provision, disable, reset

```sh
# Deployed host (paths come from /etc/shopsearch/shopsearch.env; the CLI defaults to the
# repository-local database for development):
.venv/bin/python -m backend.auth.cli --database /var/lib/shopsearch/shopsearch.sqlite3 \
  --store-id live-store create --username alice
.venv/bin/python -m backend.auth.cli --store-id live-store list
.venv/bin/python -m backend.auth.cli --store-id live-store disable --username alice
.venv/bin/python -m backend.auth.cli --store-id live-store reset --username alice
```

The store must already exist in the registry: the runtime never provisions stores, and
`--database` must point at the same file `SHOPSEARCH_DATABASE` names. No credential,
salt, token or secret is committed to the repository; the service itself needs no
secret to start (it has no Flask client-side session and no `SECRET_KEY`).

- Passwords are read from an interactive prompt and confirmed; they are never accepted
  as command-line arguments, so they do not enter shell history.
- `create` stores PBKDF2-HMAC-SHA256 with a random 16-byte salt and 600,000 iterations.
  The salt, digest and iteration count are stored per account; the password is not.
- `disable` fails authentication and immediately stops that merchant's sessions from
  authorizing anything. `reset` writes a new credential and revokes every existing
  session for that merchant.
- Deleting accounts is not implemented. Disable instead; nothing is hard-deleted.

## Sessions and cookies

- A session is an opaque 32-byte random token; only `sha256(token)` is persisted, in
  `merchant_sessions`, keyed by `(store_id, token_sha256)`.
- Sessions expire 12 hours after issue. There is no remember-me behavior: the cookie is
  a browser-session cookie and the server enforces the absolute expiry.
- The cookie is `shopsearch_merchant`, `Path=/`, `Secure`, `HttpOnly`, `SameSite=Lax`.
  Because it is `Secure`, browsers only accept it over HTTPS or on a localhost origin;
  a plain-HTTP non-local test client cannot complete the login flow.
- Signing out revokes the session row and clears the cookie. Replaying an old cookie
  after sign-out, expiry, disablement or a credential reset yields no merchant identity.

## Sign-in protection

- Sign-in and sign-out are POSTs carrying a CSRF token (the login form pairs a random
  token cookie with a hidden field; authenticated requests use the session's token).
- Five failed attempts for the same store and normalized username within 15 minutes
  throttle further attempts until that window expires. Successful authentication clears
  the counter. The counter is process-local, matching the single-process Waitress
  runtime; no shared cache is required.
- Invalid credentials return one generic message whether the username exists or not, and
  unknown usernames spend the same hashing work so response time does not reveal it.

## What this does not include

No self-service signup, no email or reset links and no roles or permission levels. A
deployed store's `/manage` can amend, hide, sell, relist and re-photograph that store's
own published items (S7/S8); a demo store stays read-only in production composition.

## The one local demonstration credential (S11)

`make demo` provisions exactly one extra account, `demo` / `demo`, and only in the
isolated, disposable local demo runtime at `data/local/form-and-field-demo/`. It is
created and re-created through this same auth machinery — normal PBKDF2 digest, normal
sessions, normal throttling, normal CSRF — and `make demo` resets it on each start so
earlier demo sessions are revoked.

It is a plainly labeled local demonstration credential, and the rules that keep it from
becoming anything else are:

- the username and password constants live only in the explicit demo composition
  (`apps/web/demo_runtime.py`), never in `backend/auth` defaults, the store record, store
  configuration, environment configuration or the deployment files;
- the deployed runtime never provisions it, never displays it and never accepts it: the
  credential exists only inside that store's demo database file;
- the sign-in page shows it only when the explicit interactive-demo capability was passed
  by `apps/web.demo`, so generic composition reveals nothing;
- a demo store remains read-only in generic composition even if an account exists for it,
  so authentication alone never grants demo mutation;
- `make demo-reset` deletes the whole runtime, including the credential and every session,
  and rebuilds it.

Do not reuse, rename or deploy this credential for a real store; provision real merchant
accounts with the CLI above.
