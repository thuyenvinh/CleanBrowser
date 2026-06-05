# CleanBrowser — Kiến trúc mục tiêu (SaaS multi-tenant)

> Tài liệu này mô tả kiến trúc đề xuất để chuyển CleanBrowser từ một ứng dụng self-hosted single-user (như hiện tại) thành một SaaS multi-tenant tương đương **gemlogin.vn** và **gpmloginapp.com**, với 4 trọng tâm: Team/Workspace + RBAC, Automation/RPA, Proxy management, Cloud sync.

---

## 1. Bối cảnh & khoảng cách

### 1.1 Hiện trạng (single-tenant)

| Layer | Stack | Ghi chú |
|---|---|---|
| Frontend | React + Vite + noVNC | State qua `useState` + polling 3s, không có Context/Redux |
| API | FastAPI single-process | Auth bằng 1 env-var `AUTH_TOKEN` (HMAC) |
| Browser engine | Playwright → CloakBrowser (Chromium patched) | 1 process / profile, KasmVNC stream |
| Persistence | SQLite (`/data/profiles.db`) + local disk `/data/profiles/{id}` | Không migration framework, không backup |
| Streaming | KasmVNC ↔ noVNC RFB proxy + CDP WS proxy | In-memory dict `BrowserManager.running` |

Pointer chính:
- `backend/database.py:34-66` — schema `profiles` + `profile_tags` (chưa có user/tenant)
- `backend/main.py:139-174` — auth middleware đơn token
- `backend/browser_manager.py:167-287` — launch flow (port/display cấp phát local)
- `frontend/src/hooks/useProfiles.ts:1-92` — state polling

### 1.2 Đối thủ tham chiếu

| Tính năng | gemlogin.vn | gpmloginapp.com |
|---|---|---|
| Profile mgmt | Unlimited / 1 license | Tags, groups, search; unlimited / license |
| Fingerprint | High score Creepjs/Pixelscan | DB fingerprint lớn, simulate hardware/canvas/WebGL/audio |
| Team/Workspace | Multi-thread, share profile | Profile sharing, sync action, **role/permission per group** |
| Automation/RPA | No-code drag-drop, **GemStore 50 module** | No-code drag-drop, **marketplace 2,000+ app / 23k installs**, full API |
| Browser core | Chromium | **Chromium + Firefox** |
| Pricing model | SaaS subscription | **Lifetime license per device** (Solo 3M, Team-5 6M, Team-20 19M) + add-on |
| Platform | Web/Desktop | Windows + macOS desktop, Private Server option |

### 1.3 Gap lớn cần đóng

1. **Không có khái niệm tenant/user/role** → blocker cho mọi tính năng team.
2. **Không có automation engine** — chỉ launch/stop thủ công, không có job scheduler, không có script runtime.
3. **Proxy chỉ là field text per-profile** — không pool, không rotation, không health-check.
4. **Profile data chỉ ở local disk** — không sync giữa máy, không backup, không versioning.
5. **Không có billing/quota/metering** — bắt buộc cho SaaS.
6. **Process launch in-process** — không scale ngang được; cần worker model.
7. **Không có audit log, observability, rate limit.**

---

## 2. Kiến trúc mục tiêu

### 2.1 Sơ đồ logic (high-level)

```
┌─────────────── Edge / CDN (Cloudflare) ───────────────┐
│                                                       │
│   ┌─────────────┐      ┌─────────────────┐            │
│   │  Web (SPA)  │◄────►│  API Gateway    │            │
│   │  React SSR  │ HTTPS│  (FastAPI)      │            │
│   └─────────────┘      │  Auth/RBAC/Quota│            │
│         ▲              └────────┬────────┘            │
│         │ WSS (VNC/CDP)         │                     │
│         │                       │ gRPC / NATS         │
│         │              ┌────────▼────────┐            │
│         │              │  Control Plane  │            │
│         │              │  - Profile svc  │            │
│         │              │  - Workspace    │            │
│         │              │  - Proxy svc    │            │
│         │              │  - Automation   │            │
│         │              │  - Billing      │            │
│         │              └────────┬────────┘            │
│         │                       │                     │
│         │              ┌────────▼─────────────┐       │
│         │              │ PostgreSQL (RLS)     │       │
│         │              │ Redis (cache/queue)  │       │
│         │              │ S3/MinIO (profile fs)│       │
│         │              │ ClickHouse (audit)   │       │
│         │              └──────────────────────┘       │
│         │                       ▲                     │
│         │                       │ NATS JetStream      │
│         │              ┌────────┴────────┐            │
│         └──────────────│ Browser Worker  │ × N        │
│       VNC/CDP tunnel   │ Pool (k8s pods) │            │
│                        │ - Chromium      │            │
│                        │ - KasmVNC       │            │
│                        │ - CDP bridge    │            │
│                        └────────┬────────┘            │
│                                 │                     │
│                        ┌────────▼────────┐            │
│                        │ Proxy Pool      │            │
│                        │ (911/BrightData │            │
│                        │  /custom)       │            │
│                        └─────────────────┘            │
└───────────────────────────────────────────────────────┘
```

### 2.2 Domain model (PostgreSQL, có Row-Level Security)

```
tenants (id, name, plan_id, created_at, status)
  │
  ├─ users (id, tenant_id, email, password_hash, mfa_secret, ...)
  │   └─ user_api_keys (id, user_id, key_hash, scopes, last_used_at)
  │
  ├─ workspaces (id, tenant_id, name, owner_user_id)
  │   └─ workspace_members (workspace_id, user_id, role)
  │       roles: owner | admin | editor | launcher | viewer
  │
  ├─ profiles (id, workspace_id, name, fingerprint_*, proxy_id, ...)
  │   ├─ profile_tags (profile_id, tag, color)
  │   ├─ profile_versions (id, profile_id, snapshot_s3_key, created_at, created_by)
  │   ├─ profile_shares (profile_id, target_user_id, permission)
  │   └─ profile_sessions (id, profile_id, worker_id, started_at, ended_at, started_by_user_id)
  │
  ├─ proxies (id, workspace_id, type, host, port, user, pass_enc,
  │           provider, rotation_url, sticky_session, last_check_at, latency_ms, status)
  │   └─ proxy_assignments (profile_id, proxy_id, sticky)
  │
  ├─ automations (id, workspace_id, name, kind)   -- kind: flow | script
  │   ├─ automation_versions (id, automation_id, dsl_json, code, language, semver)
  │   ├─ automation_runs (id, automation_version_id, profile_id, status, started_at, ended_at, log_s3_key)
  │   └─ schedules (id, automation_id, cron, enabled, next_fire_at)
  │
  ├─ subscriptions (id, tenant_id, plan_id, status, current_period_end, payment_provider_ref)
  │   └─ usage_counters (tenant_id, period, profile_count, concurrent_runs, automation_minutes, storage_gb)
  │
  └─ audit_logs (id, tenant_id, actor_user_id, action, resource_type, resource_id, ip, ua, payload_json, ts)
                 → ghi vào ClickHouse, không vào Postgres
```

**Quyết định kỹ thuật quan trọng:**

- **Postgres + RLS**: mỗi query tự động filter `tenant_id = current_setting('app.tenant_id')` — phòng leak data giữa tenant.
- **Soft delete** (`deleted_at`) cho `profiles`, `workspaces` để hỗ trợ restore + audit.
- **`profile_versions`** snapshot user_data_dir lên S3 (zstd nén) — nền tảng cho cloud sync và rollback.
- **`profile_sessions`** thay cho dict in-memory hiện tại → cho phép nhiều worker, lock theo session.

### 2.3 Auth & RBAC

| Lớp | Cơ chế |
|---|---|
| Đăng nhập | Email + password (Argon2id), MFA TOTP optional, OAuth Google/GitHub |
| Session | JWT access (15') + refresh token (rotate, 30 days) lưu Redis |
| API key | Per-user, scope: `profile:read`, `profile:launch`, `automation:run`, `admin:*` |
| RBAC | 5 role workspace: `owner` > `admin` > `editor` > `launcher` > `viewer` |
| Tenant resolution | Subdomain `{tenant}.cleanbrowser.app` HOẶC header `X-Tenant-Id` (cho API key) |
| Per-profile share | `profile_shares` override role để share lẻ profile với 1 user khác workspace (giống GPM) |

Ma trận quyền (rút gọn):

| Action | viewer | launcher | editor | admin | owner |
|---|---|---|---|---|---|
| Xem profile, screenshot | ✓ | ✓ | ✓ | ✓ | ✓ |
| Launch / VNC view | – | ✓ | ✓ | ✓ | ✓ |
| Edit profile / fingerprint | – | – | ✓ | ✓ | ✓ |
| Quản lý proxy pool | – | – | ✓ | ✓ | ✓ |
| Mời/đuổi member | – | – | – | ✓ | ✓ |
| Đổi billing plan | – | – | – | – | ✓ |

### 2.4 Browser worker model

Vấn đề hiện tại: launch trong cùng process API → không scale, mất profile khi restart.

Đề xuất: **Worker pool tách rời**, mỗi worker là 1 pod Kubernetes / VM riêng.

- **Lifecycle**:
  1. User bấm Launch → API publish job `launch.requested` lên NATS.
  2. Scheduler chọn worker còn capacity (CPU/RAM headroom + region match) → assign session.
  3. Worker pull `user_data_dir` từ S3 (nếu có version mới hơn local cache) → giải nén.
  4. Worker chạy Chromium + KasmVNC, expose VNC/CDP qua **secure tunnel** (mTLS hoặc SSH reverse) về API gateway.
  5. API trả `{vnc_url, cdp_url}` cho client; client kết nối qua WSS.
  6. Khi đóng → worker zip user_data_dir → upload S3 → tạo `profile_version` mới.

- **Capacity**: mỗi worker chạy ~5–10 profile (RAM ~512MB/profile + KasmVNC ~150MB).
- **Region**: cho user chọn region (giảm latency VNC + match geoip proxy).
- **Idle reaper**: profile không hoạt động 30' tự stop (tránh đốt RAM SaaS).

### 2.5 Proxy management

So với hiện tại (string per profile), nâng cấp:

| Tính năng | Mô tả |
|---|---|
| Pool quản lý tập trung | Bảng `proxies` cấp workspace, gán nhiều profile dùng chung |
| Provider integration | Built-in adapter cho 911 S5, BrightData, Smartproxy, IPRoyal (rotation API) |
| Health check | Job 5'/lần kiểm `https://api.ipify.org` qua proxy → cập nhật `latency_ms`, `status` |
| GeoIP detect | Auto fill timezone/locale theo IP proxy (Maxmind DB) → giảm fingerprint mismatch |
| Sticky session | Hỗ trợ residential rotating: assign session id cố định cho profile |
| Auto-rotation | Nếu IP block (HTTP 4xx pattern) → swap proxy khác trong cùng pool |
| Encryption | Password mã hoá AES-GCM với key từ KMS, không log plaintext |

### 2.6 Automation / RPA engine

Đây là phần khác biệt lớn nhất so với CleanBrowser hiện tại. Hai mode:

#### Mode A: Visual flow (no-code, giống GemStore/GPM marketplace)

- DSL JSON dạng node graph: `node = {id, type, params, next[]}`
- Node types: `goto_url`, `click`, `type`, `wait`, `extract`, `condition`, `loop`, `solve_captcha`, `http_request`, `set_variable`, `delay_random`, `human_scroll`...
- Frontend: editor dạng React Flow (node-based UI), variable inspector, run history.
- Backend: interpreter chạy trên worker, dịch DSL → Playwright actions với humanize delay.

#### Mode B: Script (code, cho power user)

- Ngôn ngữ: TypeScript hoặc Python sandboxed.
- Runtime: container ephemeral (Firecracker / gVisor) với CDP URL của profile injected.
- API exposed: `browser`, `page`, `vars`, `secrets`, `http`, `log`.
- Quota: max execution time 30', max RAM 512MB, network egress qua proxy đã gán.

#### Job scheduling

- `schedules` table với cron expression → reconcile loop push job vào NATS.
- Trigger types: cron, webhook, manual, after-another-job.
- Concurrency control: per-workspace max parallel runs (theo plan).
- Run log: stdout/stderr + screenshot trên milestone → S3, view qua UI giống CI logs.

#### Marketplace (giống GemStore / GPM)

- `marketplace_apps` table public, version semver, install count.
- App = bundle (DSL JSON + assets + manifest required permissions).
- Revenue share cho creator (Phase 4+).

### 2.7 Cloud sync & multi-device

- **Snapshot**: mỗi lần stop browser → tar+zstd `user_data_dir` → upload S3 với key `tenant/{t}/profile/{p}/v{n}.tar.zst`.
- **Diff sync** (Phase 3): chỉ upload file thay đổi (tính sha256 từng file con) — giảm 80% bandwidth.
- **Conflict**: profile đang chạy ở worker A → user khác cố launch ở worker B → API check `profile_sessions` active → từ chối hoặc force takeover (ghi audit).
- **Desktop client** (Phase 4): Electron app pull profile từ cloud, chạy local, push snapshot lên — cho user muốn launch ngay máy mình (giống GPM Windows app).

### 2.8 Billing & metering

- **Provider**: Stripe (quốc tế) + VNPay/Momo (Việt Nam).
- **Plan model**: subscription monthly/yearly + lifetime (theo gpm) + add-on pack.
- **Limits per plan**:
  - Số profile tối đa
  - Số concurrent run
  - Automation minutes/tháng
  - Storage GB (cloud sync)
  - Số workspace member
  - Region access
- **Metering**: `usage_counters` cộng dồn theo period; cron reset cuối kỳ.
- **Hard vs soft limit**: profile count = hard (không cho tạo thêm); automation minutes = soft (vẫn chạy nhưng tính overage).

### 2.9 Observability

| Loại | Tool |
|---|---|
| Logs | OpenTelemetry → Loki |
| Metrics | Prometheus (per-worker CPU/RAM, profile count, run latency) |
| Traces | OTel → Tempo |
| Audit | Sự kiện business → ClickHouse, tra cứu qua Admin UI |
| Alerts | Grafana → PagerDuty/Telegram |
| Frontend RUM | Sentry |

---

## 3. Stack thay đổi cụ thể

| Layer | Hiện tại | Mục tiêu | Lý do |
|---|---|---|---|
| DB | SQLite | PostgreSQL 16 + RLS | Multi-tenant, transaction, JSONB cho automation DSL |
| Cache/Queue | – | Redis + NATS JetStream | Session, job queue, pub/sub cho worker |
| Object storage | local `/data` | S3 / MinIO | Cloud sync user_data_dir, log, snapshot |
| Audit/Analytics | – | ClickHouse | Tra cứu nhanh hàng triệu sự kiện |
| Auth | env token | OAuth2 + JWT + Argon2id + TOTP | Multi-user |
| API | FastAPI monolith | FastAPI gateway + service modules (vẫn mono-repo Phase 1, tách Phase 3) | Đơn giản hoá đầu, micro-service khi đủ tải |
| Worker | in-process | Pod K8s, gRPC control | Scale ngang |
| Browser | CloakBrowser only | CloakBrowser + Firefox patched (Phase 5) | Match GPM dual-core |
| Frontend state | useState + polling | TanStack Query + WebSocket subscription | Real-time update khi worker thay đổi state |
| UI | React + Tailwind | Giữ nguyên + thêm React Flow (automation) + Recharts (dashboard) | – |
| Migration | manual ALTER | Alembic | Versioned schema |

---

## 4. Roadmap phát triển (theo phase)

> **Trạng thái cập nhật ngày 2026-05-16.** Phase 0–6 đã shipped trong PR #1 (~70 commit). Items không có ☑ nghĩa là chưa làm hoặc cố tình hoãn — xem ghi chú "skip" ở mỗi phase.

### Phase 0 — Nền tảng — ✅ DONE

- [x] Migrate SQLite → PostgreSQL, dựng Alembic, viết migration cho schema cũ.
- [x] Tách `BrowserManager.running` (in-memory) → bảng `profile_sessions`.
- [x] Setup CI: pytest + vitest + docker build.
- [ ] Setup OpenTelemetry baseline. *(skip — chuyển sang Phase 7 observability)*
- [x] Refactor `backend/main.py` thành `routers/` theo domain.

### Phase 1 — Multi-tenant + RBAC — ✅ DONE

- [x] Schema: `tenants`, `users`, `workspaces`, `workspace_members`, `user_api_keys`.
- [x] Postgres RLS policies (PERMISSIVE → RESTRICTIVE với `__system__` bypass).
- [x] Auth: signup/login/MFA TOTP/OAuth Google + GitHub/email verify.
- [x] UI: tenant signup flow, workspace switcher, member invite, role picker (5 role).
- [x] Audit log baseline (Postgres + middleware).

### Phase 2 — Proxy pool nâng cao — ✅ DONE

- [x] Schema `proxies`, encrypted credentials (Fernet).
- [x] Adapter framework 5 provider: manual / 911 / BrightData / Smartproxy / IPRoyal (rotation URL + sticky session).
- [x] Health-check worker (5 phút interval, httpx).
- [x] GeoIP module (ipapi.co, country → timezone mapping).
- [x] UI: trang Proxy Pool, bulk import CSV, test connection button.
- [ ] Auto-rotation khi detect block pattern. *(skip Phase 2 — Phase 7 cần observability để detect)*
- [ ] Real HTTP integration với provider API (911 rotation API, etc.) *(scaffold only — cần test credentials)*

### Phase 3 — Cloud sync + worker tách rời — ✅ DONE (in-process)

- [x] `Worker` Protocol + `LocalWorker` impl (single-process Phase 3 phase 1).
- [ ] Worker service riêng, gRPC control plane, NATS job dispatch. *(deferred — Protocol đã có, infra cần deploy K8s/NATS)*
- [ ] mTLS tunnel cho VNC/CDP từ worker về gateway. *(deferred — only needed for remote worker)*
- [x] Snapshot user_data_dir → S3 mỗi lần stop, version control (`profile_versions`).
- [x] Region selector (env `WORKER_REGIONS`, workspace default + profile override).
- [x] Idle reaper (auto-stop sau 30' — configurable).
- [ ] Diff sync (chỉ upload file thay đổi). *(Phase 7+ optimization)*
- [ ] Conflict resolution khi cùng profile chạy 2 nơi. *(handled by `ux_profile_sessions_one_active` partial unique index)*

### Phase 4 — Automation / RPA — ✅ DONE

- [x] DSL spec + interpreter (Mode A no-code) — 10 node types: goto_url, click, type, wait, wait_seconds, extract, condition, loop, set_variable, log.
- [x] React Flow editor frontend với 10 custom node UI + drag-drop palette.
- [x] Job scheduler (cron, croniter, 60s tick) + run log viewer (modal).
- [ ] Script runtime (Mode B) — TypeScript sandbox container. *(skip Phase 4 — requires Docker isolation infra)*
- [x] Quota enforcement (concurrent runs, automation minutes) — Phase 5.
- [x] Marketplace v1: install (clone DSL vào workspace), public catalog với 3 demo app.
- [x] **AI assistant** — Anthropic Claude generate DSL từ natural language (`/api/ai/build-automation`).

### Phase 5 — Billing — ✅ DONE

- [x] Stripe integration: checkout session, customer portal, webhook handler (subscription + invoice events).
- [x] VNPay adapter (Vietnam) — HMAC SHA512 sign, one-time payment.
- [x] Plan/quota enforcement matrix: `create_profile`, `launch_profile`, `invite_member`, `run_automation` (HTTP 402 khi exceed).
- [x] Self-serve admin: BillingPage với usage bars, plan comparison grid, invoice history.
- [ ] Trial flow 14 ngày. *(skip — schema có `trial_end` nhưng không tự apply)*
- [ ] Trang status, SLA monitoring. *(skip Phase 7 observability)*

### Phase 6 — Differentiation — ✅ DONE (foundational)

- [x] Firefox dual-core (Playwright firefox dispatch, `browser_type` column).
- [x] Desktop client Electron scaffold (`desktop/` — main.js + tray + preload + electron-builder config).
- [ ] Marketplace revenue share + creator portal. *(skip — schema đủ nhưng UI creator portal chưa)*
- [ ] Mobile companion. *(skip)*
- [x] AI assistant (Phase 4 ghi nhận).

### Phase 7 — Observability + production polish (đề xuất)

Chưa làm. Đề xuất scope:
- OpenTelemetry trace + Prometheus metrics
- Sentry frontend RUM
- Status page với SLA tracking
- ClickHouse cho audit log (Postgres không scale)
- Diff sync cho profile snapshots
- Trial flow 14 ngày tự apply

---

## 5. Quyết định cần chốt sớm

Các điểm có trade-off lớn, nên chốt trước Phase 1:

1. **Browser viewer**: tiếp tục KasmVNC (đang chạy) hay đổi sang **WebRTC** (latency thấp hơn, scale tốt hơn nhưng phức tạp)?
   - Khuyến nghị: KasmVNC tới Phase 3, đo benchmark, chuyển WebRTC nếu user ở xa worker > 200ms RTT.

2. **Tenant resolution**: subdomain (`acme.cleanbrowser.app`) hay path (`/t/acme/...`)?
   - Khuyến nghị: subdomain — dễ cookie isolation, chuẩn SaaS.

3. **Pricing model**: subscription thuần (như Multilogin) hay lifetime device-based (như GPM)?
   - Khuyến nghị: subscription cho cloud, lifetime cho self-host enterprise — hai SKU song song.

4. **Worker runtime**: K8s ngay từ đầu hay docker-compose nhiều node + Nomad?
   - Khuyến nghị: docker-compose Phase 3 (đỡ phức tạp), K8s khi vượt 50 worker.

5. **Automation script language**: TypeScript hay Python?
   - Khuyến nghị: TypeScript — match Playwright JS API native, ecosystem lớn hơn cho RPA.

6. **OSS vs closed**: hiện README ghi "MIT GUI + closed binary". SaaS tier có giữ open source GUI không?
   - Khuyến nghị: giữ open self-host (giống Supabase/Plausible) — community drive growth, tier cloud thu tiền.

---

## 6. Rủi ro & mitigation

| Rủi ro | Mức độ | Mitigation |
|---|---|---|
| Cost RAM SaaS (mỗi profile 512MB) | Cao | Idle reaper aggressive, oversell 3:1, charge theo concurrent run |
| Browser fingerprint bị detect (Cloudflare update) | Cao | Đầu tư CloakBrowser binary update pipeline, test suite Creepjs/Pixelscan trong CI |
| Lạm dụng platform (spam, scam) | Cao | KYC ở plan cao, abuse detection (mass account creation pattern), tuân thủ pháp luật VN |
| Lock-in proxy provider | Trung | Adapter pattern, không hard-code |
| Migration data từ self-host cũ | Trung | Tool export → import, dual-write giai đoạn chuyển |
| Latency VNC quốc tế | Trung | Multi-region worker, WebRTC fallback |
| Compliance (GDPR, NĐ 13/2023 VN) | Trung | DPA, region pin EU, audit log đầy đủ |

---

## 7. Phụ lục — mapping feature parity

| Feature target | gemlogin | gpm | CleanBrowser hiện tại | Cần build (phase) |
|---|---|---|---|---|
| Unlimited profile | ✓ | ✓ | ✓ (limit chỉ ở disk) | Quota theo plan (P5) |
| Profile groups/tags | – | ✓ | ✓ tag | Groups (P1) |
| Fingerprint editor | ✓ | ✓ | ✓ | Bổ sung canvas/audio noise UI (P2) |
| Team workspace | – | ✓ | ✗ | P1 |
| Role permission | – | ✓ | ✗ | P1 |
| Profile sharing | ✓ | ✓ | ✗ | P1 |
| Proxy pool + provider | – | – | ✗ | P2 — *điểm khác biệt* |
| Cloud sync profile | – | ✓ private server | ✗ | P3 |
| No-code automation | ✓ GemStore | ✓ marketplace | ✗ | P4 |
| Script automation | – | ✓ API | ✓ CDP only | P4 |
| Job scheduling | – | ✓ | ✗ | P4 |
| Marketplace app | ✓ 50 | ✓ 2000+ | ✗ | P4-6 |
| Dual-core (Firefox) | – | ✓ | ✗ | P6 |
| Desktop client | ✓ | ✓ | ✗ (web only) | P6 |
| Billing self-serve | ✓ | ✓ | ✗ | P5 |
| Audit log | – | – | ✗ | P1 baseline, P3 ClickHouse |
| Multi-region | – | – | ✗ | P3 — *điểm khác biệt* |

---

## 8. Bước kế tiếp đề xuất

1. **Tuần 1**: chốt 6 quyết định ở §5, viết ADR cho từng cái.
2. **Tuần 2**: tạo issue tracker (bd theo `AGENTS.md`) cho toàn bộ Phase 0 + 1.
3. **Tuần 3**: spike PostgreSQL + RLS + tenant middleware (1 dev backend, 1 tuần).
4. **Tuần 4**: kick-off Phase 0 chính thức.

> Tài liệu này là baseline. Cập nhật khi có quyết định mới hoặc constraint thay đổi (budget, team size, deadline).
