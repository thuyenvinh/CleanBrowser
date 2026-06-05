# Security policy

## Supported versions

The `main` branch is the only actively supported release. Patches for older
tags are issued on a best-effort basis for the previous quarter only.

## Reporting a vulnerability

Please report security issues privately to **thuyenvinh@gmail.com** (or open
a GitHub Security Advisory at
`https://github.com/thuyenvinh/cleanbrowser/security/advisories/new`).

Do **not** open a public issue or pull request describing a vulnerability
before the maintainers have had a chance to ship a fix.

When reporting, include:

* Affected endpoint(s) / file paths / commit SHA.
* Reproduction steps that don't require running attacks against shared
  infrastructure.
* Impact assessment (data classes affected, prerequisites for exploitation).
* Optional: a proposed patch.

Expect an acknowledgement within 3 business days and a triage decision
within 10 business days.

## Hardening checklist for self-hosters

The defaults in `docker-compose.yml` are *minimum viable for development*.
Before exposing CleanBrowser to the public internet, audit the following:

| Setting | Why |
|---|---|
| `APP_ENV=production` | Activates `_assert_production_safety` (refuses to boot with empty `JWT_SECRET` / `COOKIE_SECURE=false` / `memory://` rate-limit storage). |
| `JWT_SECRET` ≥ 32 random bytes | Avoids the ephemeral per-process fallback. Run `python -c "import secrets;print(secrets.token_urlsafe(48))"`. |
| `COOKIE_SECURE=true` behind HTTPS | Session cookie won't transit plaintext. |
| `POSTGRES_PASSWORD` strong + unique | Compose template fails closed if this is unset. |
| `PROXY_ENCRYPTION_KEY` set (Fernet) | Proxy credentials are stored encrypted; without it they survive only until restart. |
| `RATE_LIMIT_STORAGE_URI=redis://…` | Shared counters across replicas. |
| `SCRIPT_RUNTIME_ENABLED` left unset | The script-mode automation runtime is not a true sandbox; enable only with Firecracker / gVisor / nsjail. |
| Reverse proxy enforces HTTPS + HSTS + no permissive `Access-Control-Allow-Origin` | Browser-side CSRF guards (SameSite + Origin middleware) assume same-origin deployment. |
| Container runs as non-root | The bundled `Dockerfile` does not yet drop privileges — track issue or use a wrapping image. |

## Notable defences in tree

* **RLS RESTRICTIVE** (`backend/alembic/versions/0012_rls_restrictive.py`) on
  every tenant-scoped table; `app.current_tenant_id` is pinned by
  `get_optional_user` and bypassable only via the
  `__system__` sentinel inside `system_context()` blocks.
* **Argon2id** password hashing (`backend/db_auth.py`).
* **SHA-256 hashed API keys**; plaintext shown once.
* **Stripe + VNPay webhook signature verification** (`backend/billing/`).
* **OAuth state CSRF cookie** + `Origin/Referer` middleware
  (`backend/main.py:CsrfOriginMiddleware`) for state-changing requests.
* **Path traversal guard** on the SPA catch-all (`backend/main.py:serve_spa`)
  resolves `..` and only serves whitelisted file extensions.

## Known limitations

These are tracked in the security review report and have **not** been fully
mitigated in code:

* `automation/script_runtime.py` is not a true V8 isolate; gated behind
  `SCRIPT_RUNTIME_ENABLED=true` until a real isolation primitive is wired
  in.
* The Dockerfile does not yet `USER`-drop to non-root.
* Reset-password does not invalidate pre-existing JWT sessions issued
  before the password rotated. Mitigation: rotate `JWT_SECRET` on
  incident response.
