# CleanBrowser — Bàn giao dự án

Tóm tắt cho người tiếp nhận PR #1. Đọc khoảng 5 phút.

## Tình trạng

- **Branch**: `claude/research-login-app-architecture-LNyv4` — 72 commit, sẵn sàng review/merge.
- **Phases đã shipped**: 0, 1, 2, 3, 4, 5, 6 + Phase 7 baseline (observability + E2E + trial flow).
- **Tests**: backend pytest **228 pass**, frontend vitest **16 pass**, E2E Playwright **10 scenario** scaffolded.
- **LOC**: ~18,600 Python + ~8,400 TypeScript/TSX.

## Cấu trúc thư mục

```
CleanBrowser/
├── backend/                     # FastAPI app
│   ├── alembic/versions/        # 18 migration (0001 → 0018)
│   ├── routers/                 # auth, profiles, workspaces, proxies,
│   │                            # automations, billing, marketplace, ai,
│   │                            # regions, vnc, cdp, clipboard, system
│   ├── automation/              # DSL interpreter (10 node types)
│   ├── billing/                 # Stripe + VNPay adapters
│   ├── proxy_providers/         # 5 provider adapter (manual/911/BD/Smartproxy/IPRoyal)
│   ├── db_*.py                  # Per-domain DB layer (auth, proxy, automation, etc.)
│   ├── main.py                  # FastAPI app + lifespan (4 background workers)
│   ├── browser_manager.py       # Playwright launch dispatch (Chromium + Firefox)
│   ├── middleware_rls.py        # Postgres RLS tenant context var
│   ├── proxy_health.py          # Background health-check (5min)
│   ├── automation_scheduler.py  # Cron tick (60s)
│   ├── idle_reaper.py           # Auto-stop after 30min
│   ├── telemetry.py             # OTel auto-instrumentation
│   ├── ai_assistant.py          # Anthropic Claude → DSL
│   └── tests/                   # pytest suite
├── frontend/                    # React 19 + Vite + Tailwind + React Flow
│   └── src/
│       ├── components/          # 27 components (Profile, Proxy, Automation,
│       │                        # Billing, Marketplace, Auth, FlowEditor, ...)
│       ├── hooks/               # useAuth, useProfiles, useProxies, useAutomations,
│       │                        # useSchedules, useBilling, useMarketplace, useProfileVersions
│       ├── lib/                 # api, auth, proxy, automation, billing,
│       │                        # marketplace, versions, regions, sentry
│       └── App.tsx              # 5-tab layout: profiles / proxies / automations / marketplace / billing
├── desktop/                     # Electron scaffold (Win/macOS/Linux)
├── tests/e2e/                   # Playwright (auth/profile/proxy/automation/billing specs)
├── docs/
│   ├── ARCHITECTURE.md          # Kiến trúc + roadmap (phase status)
│   ├── DEPLOYMENT.md            # Env var reference + security checklist
│   ├── SETUP.md                 # Quickstart local + VPS walkthrough
│   └── HANDOFF.md               # File này
├── docker-compose.yml           # manager + postgres
├── Dockerfile                   # Multi-stage build
└── .github/workflows/
    ├── ci.yml                   # backend pytest + frontend vitest + docker build
    └── e2e.yml                  # Playwright (manual trigger)
```

## Cheatsheet — build / run / test

```bash
# Local dev (3 terminal):
docker compose up -d postgres
cd backend && DATABASE_URL=postgresql://cleanbrowser:devpassword@localhost:5432/cleanbrowser \
  JWT_SECRET=dev uvicorn main:app --reload --port 8080
cd frontend && npm run dev     # → http://localhost:5173

# Docker compose full stack:
docker compose up -d --build   # → http://localhost:8080

# Run tests:
DATABASE_URL=...               pytest backend/tests        # → 228 pass
cd frontend                    && npx vitest run            # → 16 pass
cd tests/e2e                   && npm test                  # → 10 scenarios

# Build production:
cd frontend && npm run build   # → dist/ 692 KB total

# Migration:
cd backend && alembic upgrade head           # apply all
cd backend && alembic downgrade -1           # roll back one

# Database access (RLS bypass):
docker compose exec postgres psql -U cleanbrowser -d cleanbrowser
SET app.current_tenant_id TO '__system__';   # bypass RLS for admin queries
```

## Roadmap status

| Phase | Status | Highlight |
|---|---|---|
| 0 — Foundation | ✅ Done | Postgres+Alembic, routers split, profile_sessions, CI |
| 1 — Multi-tenant + RBAC | ✅ Done | tenants/users/workspaces, JWT, MFA TOTP, OAuth Google+GitHub, email verify, RLS RESTRICTIVE, audit log |
| 2 — Proxy pool | ✅ Done | encrypted creds, 5 provider adapter, bulk CSV import, health check 5min, GeoIP |
| 3 — Cloud sync + worker | ✅ Done (single-node) | Worker Protocol, S3 snapshot, version restore, region selector, idle reaper |
| 4 — Automation / RPA | ✅ Done | DSL interpreter (10 node), React Flow editor, cron scheduler, AI assistant, marketplace |
| 5 — Billing | ✅ Done | Stripe + VNPay + quota enforce + invoice history + 14-day Pro trial |
| 6 — Differentiation | ✅ Done | Firefox dual-core + Electron desktop scaffold + marketplace |
| 7 — Production polish | 🔶 Baseline | OTel + Sentry + E2E suite + trial flow done. Rate limiting + ClickHouse audit + status page pending. |

Xem chi tiết unchecked items trong [ARCHITECTURE.md §4](./ARCHITECTURE.md#4-roadmap-phát-triển-theo-phase).

## Next steps theo ưu tiên

### P1 — Trước go-live production
- [ ] **Rate limiting** middleware (slowapi) cho `/api/auth/login`, `/signup`, `/reset-password`, OAuth callbacks. ~3 ngày.
- [ ] **Manual E2E test pass** trên 1 instance staging — đi qua toàn bộ flow signup → billing → automation. ~2 ngày.
- [ ] **DNS + Cloudflare** với DDoS protection trước khi expose public. ~1 ngày.
- [ ] **Backup verification** — restore từ pg_dump xong → app vẫn chạy. ~1 ngày.

### P2 — Sau go-live, 1 tháng đầu
- [ ] **Script mode TypeScript sandbox** — cần Docker Firecracker isolation. ~2 tuần.
- [ ] **Marketplace creator portal** — UI submit app + revenue share. ~2 tuần.
- [ ] **Real HTTP integration** cho 911/BrightData rotation API. ~1 tuần.
- [ ] **Overage billing** — charge thêm khi vượt soft limit. ~1 tuần.

### P3 — Khi vượt 100 concurrent profile
- [ ] **Remote Worker** (gRPC/NATS) + multi-region pod. ~4 tuần.
- [ ] **Diff sync** snapshot (giảm 80% bandwidth). ~2 tuần.
- [ ] **ClickHouse cho audit log** — Postgres không scale. ~1 tuần.

### P4 — Differentiation dài hạn
- [ ] Firefox fingerprint patches (8+ tuần — đầu tư source-level).
- [ ] Mobile companion app (4 tuần).
- [ ] Auto-rotation IP block detection.

## Quyết định kiến trúc chưa chốt (ADR pending)

Xem [ARCHITECTURE.md §5](./ARCHITECTURE.md#5-quyết-định-cần-chốt-sớm) — 6 quyết định trade-off lớn cần chốt nếu deploy SaaS thật:
1. VNC viewer: KasmVNC vs WebRTC
2. Tenant resolution: subdomain vs path
3. Pricing model: subscription only vs subscription + lifetime
4. Worker orchestration: docker-compose vs K8s
5. Automation script language: TypeScript vs Python
6. OSS strategy: self-host MIT + cloud closed vs full OSS

## Risk được biết

| Risk | Impact | Mitigation |
|---|---|---|
| Chưa manual E2E test | High | Chạy E2E suite + manual smoke trước go-live |
| RLS RESTRICTIVE có thể block worker nếu quên `system_context()` | Medium | Đã wrap 3 worker chính; audit thêm khi thấy log empty |
| Stripe webhook signature chưa replay test | Medium | Dùng Stripe CLI `stripe events resend` |
| `JWT_SECRET` reset = invalidate all sessions | Low | Set 1 lần, lưu vault, không đổi |
| `PROXY_ENCRYPTION_KEY` reset = mất hết proxy | High | Backup key + cảnh báo trong DEPLOYMENT.md |
| Browser RAM tăng tuyến tính | Medium | Idle reaper tự stop sau 30min; tune `IDLE_REAPER_TIMEOUT_SECONDS` |
| Postgres không scale audit_logs | Low | ClickHouse migration plan trong roadmap Phase 7 |

## Liên hệ + tài liệu

- **Architecture**: [docs/ARCHITECTURE.md](./ARCHITECTURE.md)
- **Quickstart**: [docs/SETUP.md](./SETUP.md)
- **Env vars + security**: [docs/DEPLOYMENT.md](./DEPLOYMENT.md)
- **Original README**: [../README.md](../README.md)

## Lịch sử commit (72 commits PR #1)

```
Phase 7 baseline:
  e123a2d test(e2e): Playwright suite for auth, profile, proxy, automation, billing
  25c7a52 feat(billing): 14-day Pro trial on signup and public /pricing page
  4aab87f feat(observability): OTel backend instrumentation and Sentry frontend
  51a85d2 docs: add SETUP.md with local quickstart and VPS deployment walkthrough
  07f6c56 docs: update README with SaaS features, add DEPLOYMENT.md, mark roadmap

Phase 6 differentiation:
  bc74879 fix(marketplace): use exec_driver_sql to avoid colon param parsing in JSON seed
  260974c feat(marketplace): public app catalog and install API
  27ded5b feat(browser): dual-core engine support (Chromium + Firefox)
  2d4aabe feat(desktop): Electron wrapper scaffold and marketplace browse/install UI
  6b26c25 feat(ai): AI assistant for building automation flows from natural language

Phase 5 billing:
  8fecd85 feat(billing): invoice history with Stripe webhook persistence and UI
  012bac2 feat(billing): enforce quota on profile, launch, invite, and automation
  8fa0162 feat(billing): VNPay adapter for Vietnamese market
  3e584fb feat(billing): plans, subscriptions, usage counters schema and db layer
  1facf4d feat(billing): quota enforcement module and require_quota dependency
  ec7a857 feat(billing): subscription status, plan comparison, and Stripe portal UI
  0c2fee5 feat(billing): Stripe checkout, webhook, and customer portal

Phase 3 cloud sync + worker:
  2846d2f feat(worker): region support for workspaces and profiles
  221c77c feat(storage): profile version restore, list, delete, and download endpoints
  e8dfc73 feat(storage): snapshot user_data_dir to S3 on profile stop
  fc6ee85 feat(storage): S3-compatible storage layer and profile_versions schema
  929960c feat(worker): Worker Protocol with LocalWorker implementation
  f14b219 feat(worker): idle reaper auto-stops browsers after 30 min
  0567768 feat(storage): profile version history UI with restore button

Phase 4 automation:
  9c447ca feat(automation): React Flow visual editor for DSL
  6633d32 feat(automation): schedule HTTP API and wire schedule UI + visual/JSON toggle
  128ba06 feat(automation): frontend list, edit, run, and schedule scaffold
  b3e0dc1 feat(automation): cron-based scheduler worker (60s tick)
  8d89ccc feat(automation): run viewer modal and schedule management components
  2c08f34 feat(automation): CRUD API, version, run, and background flow executor
  9ad0fd2 feat(automation): DSL flow interpreter with 10 node types
  afc1519 feat(automation): schema, db_automation module, and Pydantic models

Phase 1 closure:
  699800a feat(security): flip RLS policies to RESTRICTIVE with system bypass
  5632483 feat(auth): OAuth login flow for Google and GitHub
  9cb6962 feat(auth): email verification flow with banner UI

Phase 1 wave 3:
  33a6459 feat(security): wire tenant ContextVar into get_db and get_optional_user
  f5eeda7 feat(security): Postgres RLS policies and tenant context propagation
  54816e6 feat(frontend): wire useAuth to real API and inject X-Workspace-Id header
  50e2874 feat(workspaces): CRUD API and member management
  5219872 feat(multi-tenant): scope profiles to user workspaces
  77ecb4a feat(audit): wire AuditMiddleware and expose user on request.state

Phase 1 wave 2:
  bda5c5f feat(auth): optional TOTP MFA (setup, enable, disable, login challenge)
  cce8c9a feat(proxy): add provider adapter framework with manual and rotating bases
  f189f56 feat(proxy): add proxies schema, encrypted credentials, and CRUD module
  e51bbfb feat(rbac): enforce role hierarchy on profile mutation endpoints
  79a65ed feat(audit): add AuditLog Pydantic model
  7cf4d47 feat(audit): add audit_logs table and audit middleware (not wired)
  f7e015c feat(auth): JWT session endpoints (signup, login, logout, me) and RBAC deps

Phase 1 wave 1:
  5b65aed feat(frontend): add multi-tenant signup, login, and workspace selector
  cdfe0ef feat(auth): add tenants, users, workspaces schema and db_auth module
  96a4ba5 fix: handle invalid UUIDs and adapt tests to Postgres syntax

Phase 0:
  b793170 feat(backend): persist browser sessions to profile_sessions table
  7d19f24 test: adapt fixtures to Postgres backend
  43eb519 refactor(backend): split main.py into routers by domain
  ea94ca8 feat(backend): migrate from SQLite to PostgreSQL with Alembic
  010b731 ci: add GitHub Actions workflow for backend, frontend, and docker build
  20aecf5 docs: add SaaS multi-tenant architecture and roadmap
```
