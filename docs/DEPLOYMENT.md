# CleanBrowser — Deployment Guide

This guide covers production deployment of the multi-tenant CleanBrowser SaaS stack built across Phases 0–6. For local single-user mode see the main [README](../README.md).

## Quick start (single-node Docker, SaaS-ready)

```bash
git clone <repo>
cd CleanBrowser
cp .env.example .env   # fill in below
docker compose up -d --build
```

Open `https://yourdomain.com` behind a reverse proxy with TLS.

## Required environment variables

| Var | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | ✅ | `postgresql://user:pass@host:5432/db` |
| `POSTGRES_PASSWORD` | ✅ (compose) | Used by the `postgres` service in `docker-compose.yml` |
| `JWT_SECRET` | ✅ | HS256 signing key for session JWTs. If unset, a per-process random key is generated (sessions die on restart). |
| `COOKIE_SECURE` | recommended | `true` in production (HTTPS only) |

## Optional integrations

### S3 cloud sync (profile snapshots)

```env
STORAGE_BUCKET=cleanbrowser-prod
STORAGE_REGION=us-east-1
STORAGE_ACCESS_KEY=...
STORAGE_SECRET_KEY=...
STORAGE_ENDPOINT=                  # leave blank for AWS; set for MinIO/Wasabi
```

Without these vars, snapshots fall back to local disk under `/data/snapshots`.

### OAuth (Google / GitHub)

Create OAuth apps with redirect URI `https://yourdomain.com/api/auth/oauth/{google|github}/callback`, then:

```env
GOOGLE_OAUTH_CLIENT_ID=...
GOOGLE_OAUTH_CLIENT_SECRET=...
GITHUB_OAUTH_CLIENT_ID=...
GITHUB_OAUTH_CLIENT_SECRET=...
```

The UI auto-hides the OAuth buttons for providers that aren't configured.

### Email verification (SMTP)

```env
SMTP_HOST=smtp.sendgrid.net
SMTP_PORT=587
SMTP_USER=apikey
SMTP_PASSWORD=...
SMTP_FROM=no-reply@yourdomain.com
SMTP_STARTTLS=true
```

Without these vars, verification emails are logged to stdout (dev mode).

### Stripe (international billing)

Create plans in Stripe, copy the `price_id` for each into the `plans` table:

```sql
UPDATE plans SET stripe_price_id = 'price_xxx' WHERE id = 'starter';
UPDATE plans SET stripe_price_id = 'price_yyy' WHERE id = 'pro';
UPDATE plans SET stripe_price_id = 'price_zzz' WHERE id = 'team';
```

Then set:

```env
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

Configure the Stripe webhook URL: `https://yourdomain.com/api/billing/webhook` listening for `customer.subscription.*` and `invoice.*`.

### VNPay (Vietnam)

```env
VNPAY_TMN_CODE=...
VNPAY_HASH_SECRET=...
VNPAY_URL=https://sandbox.vnpayment.vn/paymentv2/vpcpay.html    # or production URL
```

### AI assistant

```env
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-4-6   # optional override
```

Without a key, the `AI Build` button returns a templated placeholder flow.

### Worker regions

```env
WORKER_REGIONS=us,eu,sg,vn
```

Defaults to `local`. Profiles inherit `default_region` from their workspace; users can override per profile.

### Idle reaper tuning

```env
IDLE_REAPER_ENABLED=true
IDLE_REAPER_TIMEOUT_SECONDS=1800    # 30 min
IDLE_REAPER_TICK_SECONDS=300        # 5 min
```

### Proxy credentials encryption

```env
PROXY_ENCRYPTION_KEY=...    # 44-char urlsafe base64 (Fernet key)
```

Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. If unset, an ephemeral key is generated and the existing encrypted proxies become unreadable on next restart — set this before going live.

## Database migrations

Run on every deploy:

```bash
cd backend && alembic upgrade head
```

The `entrypoint.sh` does this automatically. Migrations 0001–0018 cover the full schema including billing, marketplace, RLS policies and Firefox support.

## Postgres RLS

Phase 1 closure enabled `RESTRICTIVE` row-level security on 9 tenant-scoped tables. The app sets the GUC `app.current_tenant_id` per request via `backend/middleware_rls.py`. Background workers (`proxy_health`, `automation_scheduler`, `idle_reaper`) wrap their DB calls in `system_context()` which sets the GUC to the sentinel `__system__` to bypass policies.

If you connect to the DB outside the app (e.g. with `psql` for debugging), policies will hide everything until you run:

```sql
SET app.current_tenant_id TO '__system__';
```

## Firefox engine (optional)

Profiles can pick `firefox` instead of the default `chromium`. The Firefox binary is not bundled — install it inside the container:

```bash
docker exec -it manager playwright install firefox
```

Without the binary, attempts to launch a Firefox profile fail with a clear error.

## Backups

- **Postgres**: standard `pg_dump` of the `cleanbrowser` database. Includes profiles, automations, billing, audit log.
- **S3 snapshots**: versioned by the storage provider — enable bucket versioning if you want point-in-time recovery.
- **Local fallback** (`/data/snapshots`): mount as a volume and back up the host directory.

## Scaling notes

- Phase 3 introduced a `Worker` Protocol; the current `LocalWorker` runs everything in-process. For >50 concurrent profiles, implement a `RemoteWorker` that publishes to NATS / gRPC and run multiple worker pods.
- The control plane (API + scheduler + reaper) is single-process and stateless except for the in-memory `BrowserManager.running` dict. Replace that dict with reads from `profile_sessions` to support API replicas.
- Postgres is the bottleneck for read-heavy ops (list profiles, list runs). Add `pgbouncer` and a read replica before horizontal scaling beyond ~10k tenants.

## Health checks

| URL | Use |
|---|---|
| `GET /api/status` | Liveness — no auth. Returns running profile count + binary version. |
| `GET /api/auth/status` | Reachability + auth posture. |

The Docker container also has a built-in `HEALTHCHECK` that hits `/api/status`.

## Security checklist before going live

- [ ] `JWT_SECRET` set to a strong random value (32+ bytes).
- [ ] `COOKIE_SECURE=true`.
- [ ] HTTPS terminator in front (Caddy / nginx / Traefik / Cloudflare).
- [ ] `PROXY_ENCRYPTION_KEY` set (otherwise stored proxies break on restart).
- [ ] Stripe webhook signing secret configured (rejects forged events).
- [ ] OAuth `redirect_uri` whitelisted in Google / GitHub consoles.
- [ ] Database backups scheduled.
- [ ] S3 bucket has versioning + lifecycle policy.
- [ ] Reverse proxy rate-limits `/api/auth/login` and `/api/auth/signup`.
- [ ] Email deliverability tested (SPF / DKIM / DMARC for `SMTP_FROM`).
- [ ] Audit log retention policy (Postgres can grow large — periodic export to S3 / ClickHouse recommended).

## Operating

- **Add a region**: extend `WORKER_REGIONS`, restart. The UI region selector picks it up on next page load.
- **Add a plan**: insert into `plans` table, set `stripe_price_id`, mark `is_public=true`.
- **Disable a tenant**: `UPDATE tenants SET status='suspended' WHERE id = '...'`. The auth dependency rejects requests from suspended tenants on the next call.
- **Force-stop all sessions**: `DELETE FROM profile_sessions WHERE ended_at IS NULL` then restart the API (the manager's `cleanup_stale_sessions()` runs on startup).
- **Replay a Stripe webhook**: use the Stripe CLI `stripe events resend <event_id>`.

## Routes overview

| Group | Prefix | Purpose |
|---|---|---|
| Auth | `/api/auth/*` | signup, login (email + OAuth), MFA, email verify, JWT session |
| Workspaces | `/api/workspaces/*` | CRUD + member management |
| Profiles | `/api/profiles/*` | CRUD, launch/stop, VNC, CDP, clipboard, snapshot versions |
| Proxies | `/api/proxies/*` | CRUD, bulk CSV import, health test |
| Automations | `/api/automations/*` | flow CRUD, runs, schedules, versions |
| AI | `/api/ai/*` | flow generation from natural language |
| Marketplace | `/api/marketplace/*` | public app catalog + install |
| Billing | `/api/billing/*` | plans, subscription, Stripe + VNPay checkout, webhooks, invoices |
| Regions | `/api/regions` | list configured regions |
| System | `/api/status`, `/api/regions` | health |

## Upgrading from Phase 0 (single-token)

If you're upgrading an existing single-token install:

1. Stop the old container.
2. Run `backend/migrate_sqlite_to_postgres.py` to copy your profiles into Postgres.
3. Start the new container with `DATABASE_URL` pointed at Postgres.
4. Create your first tenant by signing up — your existing profiles will be visible to the legacy AUTH_TOKEN path (workspace_id NULL) but won't be assigned to your new account. Assign them manually:
   ```sql
   UPDATE profiles SET workspace_id = '<your-workspace-uuid>' WHERE workspace_id IS NULL;
   ```
5. Drop `AUTH_TOKEN` from the environment once you've confirmed login works.
