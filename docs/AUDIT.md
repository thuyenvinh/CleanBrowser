# BÁO CÁO RÀ SOÁT TOÀN DỰ ÁN — CleanBrowser

**Phiên bản rà soát**: 17/05/2026 trên branch `claude/research-login-app-architecture-LNyv4` (90 commits, sau wave 20)  
**Phạm vi**: 21 migration Alembic, 13 router, ~70 API endpoint, 27 frontend component, 238 backend test, 16 frontend test

---

## A. Tóm tắt nhanh

### Mức hoàn thiện tổng thể: **~85%**

Hệ thống đã shipped **100% theo roadmap kiến trúc Phase 0-7** (xem [ARCHITECTURE.md §4](./ARCHITECTURE.md#4-roadmap-phát-triển-theo-phase)) nhưng vẫn còn các **gap nghiệp vụ cần xử lý trước khi dùng production thật**. Mức độ:

- **Core SaaS** (auth + workspace + profile + proxy): ✅ 95% sẵn sàng
- **Automation engine** (DSL + script + schedule + webhook + AI): ✅ 90% sẵn sàng
- **Billing** (Stripe + VNPay + quota + overage): 🔶 80% — VNPay chưa wire UI, overage relay chưa test với Stripe sandbox thật
- **Marketplace** (browse + install + creator portal + revenue share): 🔶 70% — install paid app không thu tiền thật (TODO Phase 8)
- **Observability** (OTel + Sentry + status page + audit log): ✅ 85% sẵn sàng
- **Mobile + Desktop**: 🔴 30% — Desktop chỉ là Electron scaffold load web URL, Mobile chưa có
- **Phân quyền**: ✅ 90% (RBAC 5 role + RLS RESTRICTIVE), thiếu admin platform-level

### Modules chính đã có
1. Authentication (signup, login, OAuth, MFA, email verify) ✅
2. Multi-tenant + RBAC (5 role) ✅
3. Profile CRUD + launch/stop + VNC/CDP ✅
4. Proxy pool + provider adapter ✅
5. Automation engine (Flow + Script + Schedule + Webhook + AI) ✅
6. Cloud sync (S3 + version + diff snapshot + restore) ✅
7. Marketplace (catalog + install + creator portal + revenue share) ✅
8. Billing (Stripe + VNPay + quota + invoice + overage) ✅
9. API Keys ✅
10. Audit log (Postgres + ClickHouse) ✅
11. Public Status Page ✅
12. Worker abstraction (LocalWorker + RemoteWorker gRPC scaffold) ✅

### Modules còn thiếu/chưa rõ
1. **Forgot password / Password reset flow** — không tìm thấy endpoint
2. **UI cho mời member workspace** — backend có, UI chưa rõ vị trí
3. **UI cho MFA setup** — backend có, không có component dedicated
4. **VNPay frontend button** — backend route có, UI chưa wire
5. **Subscription expiry handling UI** — backend pass_due chưa hiện banner block action
6. **Profile sharing cross-workspace** — schema `profile_shares` mentioned trong architecture nhưng không có table
7. **Workspace soft delete + restore** — chưa có
8. **Member self-leave workspace** — chưa có
9. **Run cancellation** — chỉ có create, không có cancel mid-flight
10. **Admin platform-level role** — chỉ có workspace-level role
11. **Custom domain CNAME white-label** — chưa có
12. **Mobile companion app** — chưa có
13. **Firefox stealth fingerprint patches** — không trong scope (binary-level)

---

## B. Danh sách module/nghiệp vụ đã phát hiện

| Module/Nghiệp vụ | Entity DB | Màn hình UI | API endpoint | Trạng thái |
|---|---|---|---|---|
| Đăng ký tài khoản | `tenants`, `users`, `workspaces`, `workspace_members`, `subscriptions` | SignupPage | `POST /api/auth/signup` | ✅ Đã ổn |
| Đăng nhập email/password | `users` | LoginPage | `POST /api/auth/login` | ✅ Đã ổn |
| OAuth Google + GitHub | `users.oauth_provider/id` | LoginPage/SignupPage buttons | `GET /api/auth/oauth/{provider}/start` + callback | ✅ Đã ổn (chưa test redirect real) |
| MFA TOTP | `users.mfa_secret` | ❌ Không có UI dedicated | `POST /api/auth/mfa/{setup,enable,disable}` | 🔶 **Thiếu UI** |
| Email verification | `users.email_verified_at`, `email_verification_tokens` | EmailVerificationBanner | `GET /verify-email`, `POST /resend-verification` | ✅ Đã ổn |
| Password reset | ❌ KHÔNG có table | ❌ KHÔNG có UI | ❌ KHÔNG có endpoint | 🔴 **CHƯA LÀM** |
| Workspace CRUD | `workspaces` | WorkspaceSelector (dropdown chuyển) | `GET/POST /api/workspaces` | 🔶 **Thiếu form create UI** |
| Member management | `workspace_members` | ❌ Không có WorkspaceDetailPage | `POST/PATCH/DELETE /api/workspaces/{id}/members` | 🔶 **Thiếu UI invite** |
| Profile CRUD | `profiles`, `profile_tags` | ProfileList + ProfileForm | `GET/POST/PUT/DELETE /api/profiles` | ✅ Đã ổn |
| Profile launch/stop | `profile_sessions` | LaunchButton, StatusIndicator | `POST /api/profiles/{id}/{launch,stop}` | ✅ Đã ổn |
| Profile VNC view | (in-process) | ProfileViewer (noVNC iframe) | `WS /api/profiles/{id}/vnc` | ✅ Đã ổn |
| CDP automation API | (in-process) | (toolbar code icon) | `WS /api/profiles/{id}/cdp[/*]` | ✅ Đã ổn |
| Profile clipboard sync | (xclip subprocess) | (built-in trong viewer) | `GET/POST /api/profiles/{id}/clipboard` | ✅ Đã ổn |
| Profile version snapshot | `profile_versions`, `profile_version_files` | ProfileVersionHistory | `GET/POST /api/profiles/{id}/versions/*` | ✅ Đã ổn |
| Proxy CRUD | `proxies` | ProxyList + ProxyForm | `GET/POST/PUT/DELETE /api/proxies` | ✅ Đã ổn |
| Proxy bulk import | (no new) | ProxyImportDialog | `POST /api/proxies/bulk` | ✅ Đã ổn |
| Proxy test | (no new) | Test button | `POST /api/proxies/{id}/test` | ✅ Đã ổn |
| Proxy health check tự động | (no new) | (status badge update) | (background worker) | ✅ Đã ổn |
| Automation CRUD | `automations`, `automation_versions` | AutomationList + AutomationForm | `GET/POST/PUT/DELETE /api/automations` | ✅ Đã ổn |
| Automation Flow editor | (DSL JSON) | FlowEditor (React Flow) | (no API — client-side) | ✅ Đã ổn |
| Automation Script mode | (in run) | AutomationForm textarea | `POST /api/automations/{id}/run` | 🔶 **Sandbox subprocess, không production-grade isolation** |
| Automation Run | `automation_runs` | RunViewer modal | `POST /run`, `GET /runs/{id}` | 🔶 **Không có cancel** |
| Schedule (cron) | `automation_schedules` | ScheduleList/Form | `POST/PUT/DELETE /api/automations/.../schedules` | ✅ Đã ổn |
| Webhook trigger | `automation_webhooks` | WebhooksSection trong AutomationForm | `POST /api/webhooks/automation/{token}` | ✅ Đã ổn (chưa pass body vào flow vars) |
| AI Assistant | (call Anthropic) | "AI Build" button modal | `POST /api/ai/build-automation` | ✅ Đã ổn |
| Marketplace browse | `marketplace_apps` | MarketplacePage | `GET /api/marketplace/apps` | ✅ Đã ổn |
| Marketplace install | `tenant_app_installs` | Install button | `POST /api/marketplace/apps/{id}/install` | 🔶 **Paid app KHÔNG thu tiền thật, chỉ ghi earning** |
| Creator submit app | `marketplace_apps.moderation_status` | MarketplaceSubmitDialog | `POST /api/marketplace/apps/submit` | ✅ Đã ổn |
| Creator dashboard | `marketplace_earnings` | MarketplaceCreatorDashboard | `GET /api/marketplace/creator/{earnings,apps}` | 🔶 **"Request payout" button disabled stub** |
| Admin moderation | (no new table) | ❌ **KHÔNG có UI** | `GET /admin/pending`, `POST /admin/apps/{id}/{approve,reject}` | 🔶 **Thiếu UI admin** |
| Billing — xem plan | `plans`, `subscriptions`, `usage_counters` | BillingPage | `GET /api/billing/subscription` | ✅ Đã ổn |
| Billing — Stripe checkout | (no new) | "Upgrade" buttons | `POST /api/billing/checkout`, webhook | ✅ Đã ổn (chưa test sandbox real) |
| Billing — VNPay | (no new) | ❌ **KHÔNG có button trên UI** | `POST /api/billing/vnpay/checkout` + return | 🔶 **Thiếu UI** |
| Billing — Stripe portal | (no new) | "Manage" button | `POST /api/billing/portal` | ✅ Đã ổn |
| Billing — Invoice history | `invoices` | InvoiceList trong BillingPage | `GET /api/billing/invoices` | ✅ Đã ổn |
| Billing — Trial flow | `subscriptions.trial_end` | (tự apply trên signup) | (internal) | 🔶 **Không có banner "trial ending soon"** |
| Billing — Overage | `overage_events` | (không hiển thị) | `POST` (internal record) + flush worker | 🔶 **UI không thông báo user** |
| Billing — Quota enforce | (via quota.py) | (lỗi 402 hiển thị trong toast) | (Depends require_quota) | ✅ Đã ổn |
| API Keys | `user_api_keys` | ApiKeysPage | `GET/POST/DELETE /api/auth/api-keys` | ✅ Đã ổn |
| Audit Log | `audit_logs` (Postgres) + ClickHouse | ❌ **KHÔNG có UI cho user** | (internal middleware write) | 🔶 **Thiếu UI view audit** |
| Status Page | `service_checks` | StatusPage (`/status`) | `GET /api/status/public` | ✅ Đã ổn |
| Region selector | `workspaces.default_region`, `profiles.region` | ProfileForm dropdown | `GET /api/regions` | 🔶 **LocalWorker không enforce region — luôn chạy local bất kể chọn gì** |
| Idle reaper | (no new) | (silent) | (background worker) | 🔶 **Chỉ dựa session age, không track activity thật** |
| Snapshot diff sync | `profile_version_files` | (silent) | (internal pack_diff) | ✅ Đã ổn |
| Remote Worker gRPC | (no new) | ❌ Không applicable UI | `worker.proto` stubs | 🔶 **Scaffold only, chưa deploy real** |

---

## C. Bảng kiểm tra CRUD

Legend: ✅ Có | ❌ Không | 🔶 Một phần | N/A Không applicable

| Entity | Thêm | Xem (list+detail) | Sửa | Xóa | Tìm/Lọc | Validate | Phân quyền | Audit | Anti-duplicate | Ràng buộc xoá | Ghi chú lỗi/thiếu |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **User** | ✅ signup | ✅ /api/auth/me | 🔶 password change qua /mfa flow only | ❌ self-delete | ❌ admin search | ✅ Pydantic + Argon2 min 8 | ✅ JWT | ✅ | ✅ email unique | N/A | **Thiếu self-delete account, change-password endpoint riêng** |
| **Tenant** | ✅ tự tạo lúc signup | 🔶 không có list (1 user = 1 tenant) | ❌ rename | ❌ tenant delete | N/A | ✅ | ❌ chưa platform admin | ✅ | N/A | N/A | **Không có UI hoặc API rename/delete tenant** |
| **Workspace** | ✅ POST /workspaces | ✅ list + detail | 🔶 chỉ qua API, không có UI form rename | ❌ KHÔNG có endpoint delete | ❌ | ✅ name min 1 | ✅ admin+ | ✅ | N/A | ❌ không check cascade trước delete (vì không có) | **THIẾU delete + rename workspace** |
| **Workspace Member** | ✅ invite | ✅ list trong WorkspaceWithMembers | ✅ PATCH role | ✅ DELETE | ❌ | ✅ role enum | ✅ admin+ | ✅ | ✅ (workspace_id+user_id PK) | ✅ last-owner protection | **Frontend invite UI KHÔNG ROTUSCAR thấy — backend OK** |
| **Profile** | ✅ ProfileForm | ✅ ProfileList + Form | ✅ ProfileForm | ✅ Delete button | 🔶 search by name in sidebar, không có sort | ✅ Pydantic + browser_type check | ✅ editor+ | ✅ | ❌ **trùng tên trong cùng workspace KHÔNG bị chặn** | ❌ delete khi đang running → 409 OK; nhưng KHÔNG cảnh báo có schedule/automation đang dùng | **Thiếu: anti-duplicate name; warning khi profile có schedule active** |
| **Profile Tag** | ✅ qua ProfileForm | ✅ qua ProfileResponse | ✅ replace toàn bộ | ✅ qua replace | 🔶 filter có thể nhưng UI mờ | ✅ | inherit profile | inherit | N/A | N/A | OK |
| **Profile Session** | ✅ tự tạo qua launch | ✅ status endpoint | ❌ không cần | ✅ tự end qua stop | ❌ | ✅ FK | ✅ inherit | ✅ | ✅ partial unique 1 active per profile | ✅ cleanup_stale_sessions on startup | OK |
| **Profile Version** | ✅ tự tạo qua snapshot | ✅ ProfileVersionHistory | ❌ không cho sửa snapshot | ✅ DELETE endpoint | ❌ list ordered version DESC | ✅ | ✅ editor+ | ✅ | ✅ (profile_id+version unique) | ✅ ON DELETE CASCADE từ profile | OK |
| **Proxy** | ✅ ProxyForm + bulk | ✅ ProxyList | ✅ ProxyForm | ✅ Delete | 🔶 filter by status | ✅ type/port/host required | ✅ editor+ | ✅ | ❌ **trùng host+port KHÔNG bị chặn** | ❌ KHÔNG cảnh báo proxy đang gán cho N profile | **Thiếu: anti-duplicate; warning trước khi xoá** |
| **Automation** | ✅ AutomationForm | ✅ AutomationList | ✅ name/desc | ✅ Delete | 🔶 search by name | ✅ name + kind enum | ✅ editor+ | ✅ | ❌ trùng name OK | ❌ delete KHÔNG check schedules/webhooks đang chạy | **Thiếu: warning delete khi có active schedule/webhook** |
| **Automation Version** | ✅ create_version | ✅ list versions | ❌ immutable (DESIGN) | ❌ không có | ❌ | ✅ kind/dsl required | ✅ editor+ | ✅ | ✅ (automation_id+version) | N/A | **Không có endpoint xoá version cũ — có thể chiếm DB** |
| **Automation Run** | ✅ POST /run | ✅ list_runs + RunViewer | ❌ immutable | ❌ không xoá | ❌ | ✅ | ✅ launcher+ run, viewer+ list | ✅ | N/A | N/A | **Thiếu CANCEL run đang chạy + cleanup old runs** |
| **Schedule** | ✅ ScheduleForm | ✅ ScheduleList | ✅ PUT | ✅ DELETE | ❌ | ✅ cron validate via croniter | ✅ editor+ | ✅ | ❌ nhiều schedule cùng cron OK | N/A | OK |
| **Webhook** | ✅ inline form | ✅ WebhooksSection | ❌ không có PUT (toggle có nhưng UI?) | ✅ DELETE | ❌ | ✅ name optional | ✅ editor+ | ✅ | ✅ token unique | N/A | **Thiếu toggle enable UI; thiếu re-generate token** |
| **API Key** | ✅ ApiKeysPage | ✅ list (token plain hidden) | ❌ scope immutable | ✅ Revoke | ❌ | ✅ name required | ✅ self only | ✅ creation only | ✅ key_hash unique | N/A | **Thiếu rotate key; thiếu update scope** |
| **Marketplace App** | ✅ submit | ✅ public list | ❌ submitter không sửa được sau submit | ❌ creator không xoá được | ✅ category filter, sort by install_count | ✅ slug regex | 🔶 admin moderation thiếu UI | ✅ | ✅ slug unique | N/A | **Thiếu: edit/delete app sau submit (creator); UI admin moderation queue** |
| **Tenant App Install** | ✅ install endpoint | ✅ list_installs | ❌ không cần sửa | ✅ uninstall | ❌ | ✅ | ✅ editor+ | ✅ | ✅ (workspace+app) | ✅ ON DELETE CASCADE | OK |
| **Marketplace Earning** | ✅ tự tạo qua install | ✅ creator dashboard | ❌ admin only updates | ❌ | ❌ | ✅ | ✅ self only | ✅ | N/A | N/A | **Thiếu: UI/API admin trigger payout** |
| **Plan** | ❌ seed-only | ✅ list_plans, list_public | ❌ admin SQL only | ❌ | ❌ | ✅ enum interval | N/A user-side | N/A | ✅ slug PK | RESTRICT FK từ subscriptions | **Thiếu UI admin sửa plan limits** |
| **Subscription** | ✅ tự tạo trial trên signup; webhook tạo từ Stripe | ✅ get_active | ✅ webhook update | ✅ cancel | ❌ | ✅ status enum | ✅ owner cho actions | ✅ | ✅ partial unique active | N/A | **Thiếu: UI hiển thị trial_end countdown; UI cancel proactive** |
| **Usage Counter** | ✅ tự tạo per period | ✅ get_or_create | ✅ increment/set/peak | ❌ | ❌ | ✅ | ✅ tenant-scoped | ❌ | ✅ (tenant+period unique) | N/A | OK |
| **Invoice** | ✅ webhook | ✅ list_invoices | ✅ webhook update | ❌ immutable | ❌ | ✅ status enum | ✅ self tenant | ✅ | ✅ provider+invoice_id unique | N/A | OK |
| **Overage Event** | ✅ emit_overage | ✅ list_for_period | ✅ mark_reported | ❌ | ❌ | ✅ | ✅ tenant | ✅ | N/A | N/A | OK |
| **Audit Log** | ✅ middleware tự | ❌ **không có UI** | N/A immutable | ✅ TTL ClickHouse 365 days | ❌ | ✅ | N/A | N/A | N/A | N/A | **Thiếu UI cho user/admin xem audit** |
| **Service Check** | ✅ status worker | ✅ aggregate trong /status/public | ❌ | ✅ cleanup_old | ❌ | ✅ | N/A public read | N/A | N/A | N/A | OK |

---

## D. Bảng kiểm tra luồng nghiệp vụ

### Luồng 1: Đăng ký + verify + trial

| Bước đúng nên có | Đã có trong code | Thiếu/Lỗi | Đề xuất |
|---|---|---|---|
| 1. User submit signup form | ✅ | | |
| 2. Tạo tenant + user + workspace | ✅ | | |
| 3. Apply trial Pro 14 ngày | ✅ `apply_signup_trial` | | |
| 4. Gửi verification email | ✅ fire-and-forget | ⚠️ Không có UI cho user resend trong khi đang signup, chỉ banner sau | OK |
| 5. Issue JWT cookie | ✅ | | |
| 6. Redirect vào app | ✅ | | |
| 7. Hiển thị banner verify email | ✅ | | |
| 8. Block một số action quan trọng nếu chưa verify | ❌ **CHƯA implement** | 🔴 User chưa verify vẫn dùng được mọi thứ | **Cần block invite member / API key / billing checkout nếu chưa verify** |
| 9. Sau 14 ngày trial hết, subscription → past_due | 🔶 Stripe webhook tự, nhưng trial tự apply KHÔNG có job auto-expire | 🔴 Nếu Stripe không có sub, trial tự cấp KHÔNG bao giờ expire — user dùng Pro forever miễn phí | **Cần background job: ALTER subscriptions SET status='past_due' WHERE status='trialing' AND trial_end < now()** |
| 10. UI cảnh báo "trial ending in N days" | ❌ KHÔNG có | 🔴 User không biết trial sắp hết | **Cần countdown banner khi trial_end - now < 3 ngày** |

### Luồng 2: Tạo profile + launch + automation

| Bước đúng nên có | Đã có | Thiếu | Đề xuất |
|---|---|---|---|
| 1. Tạo proxy | ✅ | | |
| 2. Test proxy thành ok | ✅ test endpoint | ⚠️ Không bắt buộc test trước khi gán profile | **Nên warning nếu proxy status != 'ok' khi gán** |
| 3. Tạo profile + gán proxy | ✅ | ⚠️ Profile vẫn launch nếu proxy = NULL (dùng IP server) | **Warning: "Launching without proxy will leak server IP"** |
| 4. Kiểm tra quota create_profile | ✅ 402 nếu vượt | | |
| 5. Launch profile (allocate port, spawn Chromium + VNC) | ✅ | ⚠️ KHÔNG kiểm tra region của profile có match worker available | **LocalWorker bỏ qua region — cần TODO trong Worker selector** |
| 6. Kiểm tra quota concurrent_runs khi launch | ✅ require_quota('launch_profile') | | |
| 7. Tạo Automation flow | ✅ | | |
| 8. Run automation trên profile | ✅ | ⚠️ Run KHÔNG check profile state — có thể run lúc đang stop | **Đã handle: "profile not running" → end_run failure. OK** |
| 9. Theo dõi run kết quả | ✅ Run Viewer | ⚠️ Không auto-refresh, phải nhấn Refresh tay | **Nên poll mỗi 2s khi status = queued/running** |
| 10. Stop profile khi xong | ✅ | | |
| 11. Snapshot tự tạo | ✅ `_snapshot_after_stop` | ⚠️ Snapshot ASYNC sau stop, nếu container crash trước khi upload xong → mất snapshot | **Cần graceful shutdown hook chờ snapshot hoàn thành** |

### Luồng 3: Schedule cron chạy mỗi sáng

| Bước đúng nên có | Đã có | Thiếu | Đề xuất |
|---|---|---|---|
| 1. Tạo schedule với cron + profile | ✅ | | |
| 2. Scheduler tick 60s | ✅ `automation_scheduler.py` | | |
| 3. Detect schedule due | ✅ `list_due_schedules` | | |
| 4. Tạo run | ✅ | | |
| 5. Verify profile đang running | ❌ **KHÔNG check trước khi fire** | 🔴 Schedule fire nhưng profile chưa launch → run fail "profile not running" | **Cần: schedule fire → check profile state; nếu stopped, OPTIONAL auto-launch trước rồi run; hoặc skip + log warning** |
| 6. Execute flow | ✅ `_execute_run_async` | | |
| 7. Tính next_fire_at | ✅ `_compute_next_fire` | | |
| 8. Mark_schedule_fired + set_schedule_next_fire | ✅ | | |
| 9. Nếu run fail, retry? | ❌ KHÔNG có retry logic | 🔶 Schedule chạy lần sau theo cron, không retry cùng lần | **Acceptable cho cron; nếu cần SLA cao, thêm `retry_count` per schedule** |
| 10. Nếu profile vừa bị xoá thì schedule | ✅ FK ON DELETE CASCADE | | OK |

### Luồng 4: User upgrade từ Free lên Pro qua Stripe

| Bước đúng nên có | Đã có | Thiếu | Đề xuất |
|---|---|---|---|
| 1. User click "Upgrade" Pro | ✅ BillingPage | | |
| 2. Backend tạo Stripe Checkout Session | ✅ | | |
| 3. Redirect Stripe | ✅ | | |
| 4. User pay → Stripe webhook customer.subscription.created | ✅ handle_event | | |
| 5. Backend persist subscription | ✅ | | |
| 6. Subscription cũ (trialing) bị overwrite hay giữ song song? | ⚠️ **Logic ko rõ**: code dùng `create_subscription` nếu chưa có. Partial unique cho phép 1 active. Nếu trial active và Stripe sub mới active → vi phạm unique? | 🔴 **Possible bug**: partial unique `ux_subscriptions_active` chỉ cho 1 row WHERE status IN active/trialing/past_due. Stripe webhook thêm row có thể conflict | **Test thực tế: signup → wait → upgrade qua Stripe → check subscriptions table. Nếu 2 row active → bug**. Fix: trước khi tạo từ webhook, cancel existing trial sub |
| 7. Redirect về app | ✅ | | |
| 8. BillingPage reload → hiện Pro | ✅ qua refresh | | |
| 9. Quota apply Pro limits | ✅ qua `get_tenant_limits` | | |

### Luồng 5: Install marketplace app paid

| Bước đúng nên có | Đã có | Thiếu | Đề xuất |
|---|---|---|---|
| 1. User browse marketplace | ✅ | | |
| 2. Click "Install" trên paid app (price_cents > 0) | ✅ | | |
| 3. Show payment dialog | ❌ **KHÔNG có** | 🔴 User click → install ngay, không trả tiền | **TODO trong code: "Payment collection deferred to Phase 8"** |
| 4. Charge buyer | ❌ KHÔNG có | 🔴 | **Cần Stripe Checkout one-time payment + verify trước khi install** |
| 5. Record earning cho creator | ✅ `record_earning` chạy | ⚠️ Ghi nhận creator được tiền nhưng buyer KHÔNG trả → debt mất | **Critical bug: chỉ record earning sau khi buyer payment confirmed** |
| 6. Clone DSL vào automation buyer | ✅ | | |
| 7. Available sau 14 ngày | ✅ logic có | | |
| 8. Admin trigger payout | ❌ KHÔNG có UI / endpoint | 🔴 Creator không nhận được tiền | **TODO Phase 8: payout flow** |

### Luồng 6: Stripe overage flush

| Bước đúng nên có | Đã có | Thiếu | Đề xuất |
|---|---|---|---|
| 1. User vượt quota automation_minutes | ✅ check_quota trả `is_overage=true` | | |
| 2. Record event vào overage_events | ✅ emit_overage | ⚠️ Chỉ áp dụng cho `run_automation` | OK |
| 3. Background worker 60s | ✅ overage_worker | | |
| 4. Worker fetch unreported | ✅ | | |
| 5. Resolve subscription_item_id | ✅ get_subscription_overage_item | ⚠️ Nếu subscription chưa setup overage line item Stripe-side → field NULL → skip event | **Cần admin tool: setup overage line item Stripe → save subscription_item_id**. Hiện không có UI. |
| 6. POST Stripe Usage Record với idempotency | ✅ | | |
| 7. Mark_reported | ✅ | | |
| 8. Retry nếu fail | ✅ leave reported=false, next tick lại | | OK |
| 9. Trialing user có bị charge overage? | ⚠️ **Logic không clear**: `apply_overage` gates trên `plan.allow_overage` chứ không check status. Trialing với plan Pro → có thể overage charge nếu vượt | 🔴 **Potential bug**: user trial Pro vượt 3000 min → bị charge overage dù chưa pay! | **Fix: thêm condition `if subscription.status == 'active'` mới relay** |

---

## E. Bảng kiểm tra trạng thái

### Đối tượng có state machine

| Đối tượng | Trạng thái hiện có | Khởi tạo | Chuyển bởi ai | Điều kiện chuyển | Trạng thái cuối | Lỗi/điểm thiếu |
|---|---|---|---|---|---|---|
| **profile_sessions** | `starting` → `running` → `stopped`/`crashed` | `starting` lúc launch | system (browser_manager) | spawn process xong → running; stop user → stopped; crash → crashed | `stopped`/`crashed` | ⚠️ **Không có trạng thái `pending` để queue khi worker capacity hết. Hiện launch fail trực tiếp** |
| **automation_runs** | `queued` → `running` → `success`/`failure`/`cancelled` | `queued` khi POST /run | background task | task starts → running; ngon → success; lỗi → failure | success/failure/cancelled | ⚠️ **`cancelled` có trong enum nhưng KHÔNG có endpoint cancel** — user không thể dừng run đang chạy |
| **subscriptions** | `active`, `trialing`, `past_due`, `cancelled`, `expired` | `trialing` trên signup; `active` từ Stripe webhook | webhook hoặc cancel API | Stripe events; manual cancel | `cancelled`/`expired` | 🔴 **Không có job auto-flip `trialing` → `past_due` khi `trial_end` qua. Stripe webhook chỉ flip cho Stripe sub, KHÔNG cho trial tự apply** |
| **marketplace_apps** | `approved`, `pending`, `rejected` | `pending` khi submit; `approved` cho seed apps | admin approve/reject | manual | (terminal: `approved` hoặc `rejected`) | ⚠️ **KHÔNG có UI cho admin moderation queue. Phải sửa SQL trực tiếp** |
| **marketplace_earnings** | `pending` → `available` → `paid_out` HOẶC `refunded` | `pending` khi install | system (timer cho available); manual cho paid_out | available_at <= now → available; admin trigger payout | `paid_out` hoặc `refunded` | 🔴 **Không có job auto-flip `pending` → `available`. `mark_earnings_available_due` helper có nhưng chưa wire vào worker** |
| **overage_events** | `reported=false` → `reported=true` | `false` khi emit | overage_worker | flush thành công | `reported=true` | OK |
| **invoices** | `paid`, `open`, `failed`, `void`, `uncollectible`, `draft` | từ Stripe webhook | webhook | Stripe events | `paid`/`failed`/`void` | OK |
| **service_checks** | `ok`, `degraded`, `down` | mỗi tick | status_worker | latency + HTTP code | (rotating history) | OK |
| **automation_webhooks** | `enabled=true/false` | true khi create | toggle endpoint | manual | (no terminal) | ⚠️ **Toggle endpoint có nhưng UI thiếu** |
| **profile_versions** | `snapshot_kind='full'/'diff'` | full hoặc diff khi snapshot | system | algorithm | (immutable sau create) | OK |

### Bị kẹt trạng thái?
- 🔴 **profile_sessions** có thể kẹt `running` nếu container crash trước khi `end_session` chạy → `cleanup_stale_sessions` chạy ở startup là OK, NHƯNG nếu user reload nhanh giữa crash + restart sẽ thấy status `running` sai
- 🔴 **automation_runs** kẹt `queued` nếu background task crash trước khi mark_running. Không có timeout.
- 🔴 **subscriptions trialing** không tự expire — **BUG NGHIÊM TRỌNG cho doanh thu**

---

## F. Danh sách lỗi/rủi ro nghiêm trọng

### Critical (gây sai dữ liệu, mất dữ liệu, sai bảo mật, thất thu doanh thu)

| ID | Mô tả | Hậu quả | File liên quan |
|---|---|---|---|
| C1 | **Trial Pro không tự expire** — `subscriptions.trial_end < now()` nhưng status vẫn `trialing` mãi mãi | User dùng Pro miễn phí vĩnh viễn, thất thu lớn | `db_billing.py`, cần thêm `expire_trial_subscriptions` worker |
| C2 | **Install marketplace paid app KHÔNG thu tiền** — `record_earning` chạy nhưng buyer không trả gì | Creator nghĩ có tiền, platform debt creator, không có doanh thu | `routers/marketplace.py:install_app` |
| C3 | **Trialing user có thể bị charge overage** — relay không check status | User trial bị charge sai → complaints + refund | `billing/overage.py:report_to_stripe` |
| C4 | **Stripe webhook tạo sub mới khi user đã có trial sub active** — vi phạm partial unique `ux_subscriptions_active` | 500 error, webhook fail, sub không update | `routers/billing.py:stripe_webhook` |
| C5 | **AuditMiddleware không wrap trong system_context** | RLS RESTRICTIVE có thể block insert audit khi user chưa resolved | `middleware_audit.py` |
| C6 | **Forgot password flow CHƯA tồn tại** | User mất password = mất tài khoản, không tự reset được | Cần endpoint mới |
| C7 | **Profile owner-only check không có** — bất kỳ editor nào trong workspace đều có thể delete profile của người khác | Nhân viên malicious xoá profile của manager | Có thể thêm `owner_user_id` vào profile + check trước delete |

### High (làm hỏng quy trình chính)

| ID | Mô tả | Hậu quả | File |
|---|---|---|---|
| H1 | **Schedule fire nhưng profile chưa launch** | Run liên tục failure, user không hiểu vì sao | `automation_scheduler.py` cần check profile state hoặc auto-launch |
| H2 | **Run không thể cancel** | User trigger nhầm run dài 30 phút, không có cách dừng → tốn quota minutes | Cần `POST /api/automations/runs/{id}/cancel` |
| H3 | **LocalWorker bỏ qua region** profile chọn `us-east` nhưng chạy `local` | User trả Pro để có multi-region, nhưng thực tế chỉ 1 region | `worker.py:LocalWorker.launch` ignore region; cần WorkerPool với region routing |
| H4 | **Marketplace earnings không auto-flip available** sau 14 ngày | Creator thấy số "available" = 0 mãi | `db_marketplace.mark_earnings_available_due` cần wire vào worker |
| H5 | **Webhook trigger không pass body data vào flow vars** | External service gửi data nhưng flow không dùng được | `routers/webhooks.py` cần inject body vào `RunContext.variables` |
| H6 | **Snapshot async không await trước container shutdown** | Stop container giữa chừng → mất snapshot version mới nhất | `browser_manager.py:_snapshot_after_stop` cần track + lifespan wait |
| H7 | **Container restart làm mất profile_sessions in-memory `browser_mgr.running`** dù DB đã cleanup. User reload thấy badge "stopped" nhưng process Xvnc/Chromium thật sự dead | `idle_reaper` không xử lý orphan process trên disk | Cần kill orphan Xvnc/Chromium ở startup |
| H8 | **Banner email verify chỉ là warning, không block action quan trọng** | Spam signup → spam email gửi | Cần block invite + API key creation + billing nếu chưa verify |
| H9 | **Profile rename không validate trùng tên trong workspace** | Confusion khi 5 profile cùng tên `test` | Constraint UNIQUE (workspace_id, name) hoặc warning UI |

### Medium (gây khó dùng hoặc thiếu kiểm tra)

| ID | Mô tả | File |
|---|---|---|
| M1 | UI quản lý MFA setup không có dedicated page | Cần thêm `MfaSetupPage.tsx` |
| M2 | UI mời member workspace không rõ vị trí | Cần thêm `WorkspaceMembersPage.tsx` |
| M3 | UI VNPay checkout button không có | Frontend `BillingPage.tsx` thiếu nút "Pay with VNPay" |
| M4 | UI hiển thị trial countdown banner | `BillingPage.tsx` hoặc App-level banner |
| M5 | UI admin moderation marketplace | Cần `AdminPanel.tsx` mới |
| M6 | UI cancel run đang chạy | Backend chưa có, UI cũng chưa |
| M7 | RunViewer không auto-refresh khi run đang chạy | Cần poll mỗi 2s |
| M8 | Proxy delete không cảnh báo có N profile đang dùng | `ProxyPage.tsx` confirm dialog |
| M9 | Automation delete không cảnh báo có schedule/webhook active | `AutomationPage.tsx` |
| M10 | Workspace delete + rename UI chưa có | Cần WorkspaceSettings page |
| M11 | API key không thể rotate (phải tạo mới + revoke cũ) | UX không tiện |
| M12 | Profile search sidebar chỉ filter name, không tag/region | `ProfileList.tsx` extend |
| M13 | Bulk import CSV không hiển thị preview chi tiết lỗi | `ProxyImportDialog.tsx` |
| M14 | AI Build modal không cho user save prompt đã dùng | Tiện cho rebuild |

### Low (cải thiện UI/UX)

| ID | Mô tả |
|---|---|
| L1 | Không có dark/light mode toggle (mặc định dark) |
| L2 | Không có i18n — text Anh + Việt mix tùy chỗ |
| L3 | Mobile responsiveness không test |
| L4 | Toast notifications không có (dùng alert/banner) |
| L5 | Loading skeleton thiếu — chỉ "Loading..." text |
| L6 | Form không có "unsaved changes" warning khi user navigate away |
| L7 | Keyboard shortcuts thiếu |
| L8 | Tooltip cho icon button chưa đầy đủ |

---

## G. Đề xuất xử lý

| Ưu tiên | Vấn đề | Cần sửa gì | File chính | Ảnh hưởng | Cần test? |
|---|---|---|---|---|---|
| 🔴 P0 | C1 — Trial không expire | Tạo worker `trial_expiry_worker.py` chạy mỗi 1h: `UPDATE subscriptions SET status='past_due' WHERE status='trialing' AND trial_end < now()` | `backend/trial_expiry_worker.py` (NEW) + `main.py` startup hook | DB schema, quota system | ✅ pytest |
| 🔴 P0 | C2 — Paid install không thu tiền | Thêm Stripe Checkout one-time flow trước khi `record_earning` + clone DSL | `routers/marketplace.py:install_app` | Stripe, db_marketplace | ✅ E2E |
| 🔴 P0 | C3 — Trialing user bị overage charge | Thêm `if sub.status == 'active'` trong `apply_overage` | `billing/overage.py:emit_overage` | quota.py | ✅ unit |
| 🔴 P0 | C4 — Webhook tạo sub mới khi đã có trial | Trong `stripe_webhook` cho `subscription.created`: cancel existing trial sub TRƯỚC khi insert mới | `routers/billing.py:stripe_webhook` | db_billing | ✅ E2E |
| 🔴 P0 | C5 — AuditMiddleware không system_context | Wrap `db_audit.write()` trong `with system_context():` trong middleware | `middleware_audit.py` | audit_logs | ✅ unit |
| 🔴 P0 | C6 — Forgot password | Thêm endpoints: `POST /forgot-password` (gửi reset token email), `POST /reset-password` (verify token + set new password); thêm table `password_reset_tokens` | `alembic/0026`, `routers/auth.py`, `email_sender.py` | users | ✅ E2E |
| 🔴 P0 | C7 — Editor có thể xoá profile của người khác | Thêm cột `created_by_user_id` vào profiles + check tự delete only HOẶC admin role | `alembic/0027`, `database.py`, `routers/profiles.py` | RBAC | ✅ unit |
| 🟠 P1 | H1 — Schedule fire nhưng profile stopped | Trong `_fire_schedule`: nếu profile stopped, log skip + KHÔNG tạo run failure; HOẶC option `auto_launch_on_fire` trong schedule | `automation_scheduler.py`, `db_automation.py` (thêm option) | profile, automation_runs | ✅ unit |
| 🟠 P1 | H2 — Run cancel | Thêm `POST /api/automations/runs/{id}/cancel` set status='cancelled' + kill background task qua asyncio.Task store | `routers/automations.py` | runs | ✅ unit |
| 🟠 P1 | H4 — Earnings không auto available | Wire `mark_earnings_available_due` vào job mỗi 1h (có thể vào `trial_expiry_worker.py` chung) | `trial_expiry_worker.py` | marketplace_earnings | ✅ unit |
| 🟠 P1 | H6 — Snapshot mất khi shutdown | Track active snapshots trong dict; trong `cleanup_all`, await all pending | `browser_manager.py` | profile_versions | ✅ integration |
| 🟠 P1 | H7 — Orphan Xvnc/Chromium process | Startup cleanup: `pkill -f Xvnc; pkill -f chromium` HOẶC track PID trong DB và kill từng cái | `browser_manager.py:cleanup_stale` | profile_sessions | ✅ integration |
| 🟠 P1 | H8 — Email verify không block | Thêm dependency `require_verified_email` cho invite/API key/billing | `dependencies.py`, các route nhạy | users | ✅ unit |
| 🟡 P2 | M1-M5 — UI thiếu (MFA, Members, VNPay, Trial banner, Admin moderation) | Tạo 5 component mới + wire vào App.tsx | `frontend/src/components/*` | UX | ✅ Playwright |
| 🟡 P2 | M6 — UI cancel run | Sau khi H2 backend xong, thêm "Cancel" button trong RunViewer | `RunViewer.tsx` | run lifecycle | |
| 🟡 P2 | M7 — Auto-refresh run | Poll mỗi 2s khi status queued/running trong useRun hook | `useAutomations.ts` | UX | |
| 🟡 P2 | M8-M9 — Confirm dialog có impact info | Hiện list profile/automation ảnh hưởng trước delete | `Proxy/AutomationPage.tsx` | UX | ✅ Playwright |
| 🟡 P2 | M10 — Workspace settings UI | Tạo WorkspaceSettingsPage với rename + delete + member management | `frontend/components` | workspace | ✅ E2E |
| 🟢 P3 | L1-L8 — UI polish | Theme system, i18n, mobile breakpoints, toast lib, loading skeleton | Toàn bộ frontend | UX | |

---

## H. Đề xuất test cần viết

### Unit test (backend, pytest)
1. **`test_trial_expiry.py`** — trial subscription tự expire khi quá hạn
2. **`test_overage_skip_trial.py`** — verify trialing user KHÔNG bị overage charge
3. **`test_quota_concurrent_runs_real.py`** — count_running query đúng cross-workspace cùng tenant
4. **`test_record_usage_post_increment.py`** — verify increment + overage emit chạy đúng thứ tự
5. **`test_audit_middleware_with_rls.py`** — verify audit write thành công cả khi không có request.state.user
6. **`test_forgot_password_flow.py`** — gen token + verify + reset
7. **`test_password_reset_token_expiry.py`** — token quá 24h từ chối
8. **`test_marketplace_install_paid_requires_payment.py`** — không cho install paid app nếu chưa pay
9. **`test_schedule_skip_when_profile_stopped.py`** — schedule fire log skip thay vì fail
10. **`test_run_cancel_endpoint.py`** — cancel set status='cancelled' và task được kill
11. **`test_workspace_delete_blocks_when_members.py`** — confirm hoặc cascade
12. **`test_profile_anti_duplicate_name.py`** — không tạo 2 profile cùng tên cùng workspace

### Integration test (backend + DB)
1. Stripe webhook idempotency: replay same event 3 lần → 1 sub created
2. RLS: query với tenant context A → KHÔNG thấy data tenant B
3. RLS với system_context → thấy tất cả
4. Snapshot diff chain restore: tạo v1 full, v2-v9 diff, restore v9 → đúng state v9
5. Bulk import 500 proxy partial fail (5 invalid) → 495 created, 5 reported
6. OAuth callback Google: mock provider trả userinfo → user mới được tạo + link

### Playwright E2E test (đã có 10, đề xuất thêm)
1. `verify-email.spec.ts` — signup → click link verify → banner mất
2. `mfa.spec.ts` — setup MFA → enable → logout → login với code
3. `oauth.spec.ts` — mock Google OAuth → callback → vào app
4. `forgot-password.spec.ts` — request reset → click link → set new password → login với password mới
5. `trial-expiry-banner.spec.ts` — fake trial_end = now+1day → banner hiện
6. `quota-exceeded-create-profile.spec.ts` — tạo 10 profile (Free limit) → cái 11 fail 402
7. `marketplace-install.spec.ts` — install free app → automation xuất hiện trong workspace
8. `run-cancel.spec.ts` — start run dài → click Cancel → status='cancelled'
9. `member-invite.spec.ts` — invite email → user thấy workspace trong selector
10. `schedule-fire.spec.ts` — tạo schedule mỗi phút, đợi 1.5 phút, verify ≥ 1 run

### Test phân quyền (matrix)
- 5 role × 13 nghiệp vụ chính = 65 case
- Verify viewer NOT MUTATE
- Verify launcher CANNOT EDIT but CAN LAUNCH
- Verify editor CAN MUTATE but NOT INVITE
- Verify admin CAN INVITE but NOT BILLING
- Verify owner CAN BILLING

### Test luồng end-to-end (chính)
1. **Signup → trial → upgrade Stripe** — verify subscription transition
2. **Tạo proxy → tạo profile → launch → automation → stop → snapshot** — full happy path
3. **Schedule cron → fire → run success → run log có entry** — automation pipeline
4. **Webhook external trigger → run created → flow chạy** — webhook pipeline
5. **API key tạo → curl với key → trả profile list** — API authentication

### Test lỗi dữ liệu
1. Submit form với SQL injection trong tên profile → escaped đúng
2. Submit XSS trong notes → sanitized
3. JWT expired → 401 + redirect login
4. Webhook signature sai → 400 reject
5. Race: 2 user cùng workspace delete cùng profile → 1 success 1 404

---

## I. Kết luận

### Dự án đã sẵn sàng dùng thử chưa?
**✅ CÓ** — cho **internal beta + demo + showcase**. Đủ ổn để 5-10 tester team nội bộ chạy thử các flow chính.

### Có thể deploy production chưa?
**❌ CHƯA**, cần xử lý **7 bug Critical** trước khi cho khách hàng thật signup + pay. Đặc biệt:
- C1 (trial không expire) → thất thu doanh thu trực tiếp
- C2 (paid install không charge) → ảnh hưởng creator revenue + reputation
- C6 (forgot password) → user mất account = customer support nightmare
- C7 (editor xoá profile người khác) → data loss / abuse trong team

### Bắt buộc làm trước khi go-live thật (P0)

1. **Fix 7 bug Critical** (C1-C7) — ~1 tuần
2. **Manual E2E QA pass** trên staging với data thật, 1 SDET — 3 ngày
3. **Stripe sandbox test thực sự** với CLI replay webhook + verify subscription state — 1 ngày
4. **Backup verification** — restore từ pg_dump → app vẫn chạy — 1 ngày
5. **DNS + Cloudflare DDoS** + HTTPS cert — 1 ngày
6. **Set tất cả env var production** (JWT_SECRET, PROXY_ENCRYPTION_KEY, Stripe live keys, S3 bucket, SMTP, OAuth client IDs) — 1 ngày
7. **Pricing public page test với cards thật** — 1 ngày
8. **Setup monitoring real**: status page + Sentry + OTel collector + email alerts — 2 ngày

**Tổng**: ~2 tuần với team 2-3 dev + 1 QA.

### Bắt buộc làm trong tháng đầu sau go-live (P1)

1. Fix 8 bug High (H1-H9)
2. Wire 5 UI thiếu (MFA setup, Members invite, VNPay button, Trial banner, Admin moderation)
3. Run cancel + auto-refresh run viewer
4. Anti-duplicate profile/proxy name
5. Workspace settings UI
6. Email verify enforcement
7. Email forgot password đầy đủ flow
8. Stripe overage live test với account thật

### Nên cải thiện sau (P2-P3)

1. Toast notification system (thay alert/banner)
2. Loading skeleton thay "Loading..."
3. Mobile responsive
4. Dark/Light mode toggle
5. i18n cho Việt + Anh
6. Keyboard shortcuts (j/k navigate, n new, etc.)
7. Tooltip cho icon buttons
8. AI Build save prompts history
9. Marketplace creator earning charts
10. Workspace audit log UI viewer

### Nghiệp vụ cần xác nhận lại với business

Các câu hỏi cần hỏi product owner trước khi sửa:

1. **Trial expiry: nên downgrade về `past_due` hay `expired`?** Sự khác nhau cho user là gì? Có nên block action hay chỉ giảm quota?
2. **Free plan có cho dùng overage không?** Hiện tại KHÔNG. Có thay đổi?
3. **Marketplace paid app: dùng Stripe one-time hay subscription?** Mỗi install có thể là perpetual license hay yearly?
4. **Creator payout: minimum threshold bao nhiêu?** ($10, $50)? Tần suất (monthly, weekly)?
5. **OAuth: cho phép user link cùng email với cả Google + GitHub + email/password?**
6. **MFA bắt buộc khi nào?** Cho owner role? Tùy chọn cho mọi user?
7. **Workspace delete: hard delete hay soft delete?** Recovery window bao lâu?
8. **Audit log retention: 30 ngày Postgres + 365 ngày ClickHouse có đủ compliance?** GDPR yêu cầu khác?
9. **Region routing: nếu profile chọn `us-east` nhưng worker us-east hết capacity, fallback `eu` hay refuse?**
10. **Run cancel: tính minute đến lúc cancel hay refund toàn bộ?**

---

## TODO list ưu tiên cho developer

```
[ ] C1: trial_expiry_worker.py + main.py startup        (1 day)
[ ] C2: stripe one-time checkout cho marketplace        (3 days)
[ ] C3: overage skip trialing                            (0.5 day)
[ ] C4: webhook cancel trial sub trước khi tạo Stripe sub (0.5 day)
[ ] C5: audit middleware wrap system_context             (0.5 day)
[ ] C6: forgot password full flow (table+endpoint+UI+email) (2 days)
[ ] C7: profile owner check                              (1 day)
[ ] H1: schedule check profile state                     (1 day)
[ ] H2: run cancel endpoint + UI                         (2 days)
[ ] H3: workerpool region routing (or doc as known)      (3 days)
[ ] H4: earnings available worker                        (0.5 day)
[ ] H5: webhook body → flow vars                         (1 day)
[ ] H6: graceful snapshot wait on shutdown               (1 day)
[ ] H7: kill orphan Xvnc/Chromium at startup             (1 day)
[ ] H8: require_verified_email dependency                (1 day)
[ ] H9: anti-duplicate profile/proxy name                (0.5 day)
[ ] M1: MfaSetupPage.tsx                                 (1 day)
[ ] M2: WorkspaceMembersPage.tsx                         (2 days)
[ ] M3: VNPay UI button                                  (0.5 day)
[ ] M4: Trial countdown banner                           (0.5 day)
[ ] M5: Admin moderation panel                           (2 days)
[ ] M6+M7: Run cancel + auto-refresh                     (1 day)
[ ] M8+M9: Delete impact confirm dialogs                 (1 day)
[ ] M10: Workspace settings page                         (2 days)
[ ] Test write: 12 unit + 6 integration + 10 Playwright  (5 days)

Tổng P0+P1 + tests: ~30 ngày × 1 dev hoặc ~12 ngày với 3 dev parallel
```

---

**Báo cáo này được lập trên branch `claude/research-login-app-architecture-LNyv4` (90 commits). Khi merge xuống main, refresh lại các path file và line number cho chính xác.**
