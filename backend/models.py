"""Pydantic models for profile CRUD operations."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


class ProfileCreate(BaseModel):
    name: str
    fingerprint_seed: int | None = None  # random if not set
    proxy: str | None = None  # legacy "http://user:pass@host:port" or null
    proxy_id: str | None = None  # FK into proxies pool; preferred over ``proxy``
    timezone: str | None = None  # "America/New_York"
    locale: str | None = None  # "en-US"
    platform: Literal["windows", "macos", "linux"] = "windows"
    user_agent: str | None = None
    screen_width: int = 1920
    screen_height: int = 1080
    gpu_vendor: str | None = None
    gpu_renderer: str | None = None
    hardware_concurrency: int | None = None
    humanize: bool = False
    human_preset: Literal["default", "careful"] = "default"
    headless: bool = False
    geoip: bool = False
    clipboard_sync: bool = True
    auto_launch: bool = False
    color_scheme: Literal["light", "dark", "no-preference"] | None = None
    launch_args: list[str] = Field(default_factory=list)
    notes: str | None = None
    region: str | None = None
    browser_type: Literal["chromium", "firefox"] = "chromium"
    tags: list[TagCreate] | None = None


class ProfileUpdate(BaseModel):
    name: str | None = None
    fingerprint_seed: int | None = None
    proxy: str | None = Field(default=None)
    proxy_id: str | None = Field(default=None)
    timezone: str | None = Field(default=None)
    locale: str | None = Field(default=None)
    platform: Literal["windows", "macos", "linux"] | None = None
    user_agent: str | None = Field(default=None)
    screen_width: int | None = None
    screen_height: int | None = None
    gpu_vendor: str | None = Field(default=None)
    gpu_renderer: str | None = Field(default=None)
    hardware_concurrency: int | None = Field(default=None)
    humanize: bool | None = None
    human_preset: Literal["default", "careful"] | None = None
    headless: bool | None = None
    geoip: bool | None = None
    clipboard_sync: bool | None = None
    auto_launch: bool | None = None
    color_scheme: Literal["light", "dark", "no-preference"] | None = Field(default=None)
    launch_args: list[str] | None = None
    notes: str | None = Field(default=None)
    region: str | None = Field(default=None)
    browser_type: Literal["chromium", "firefox"] | None = None
    tags: list[TagCreate] | None = None


class TagCreate(BaseModel):
    tag: str
    color: str | None = None  # hex color


class TagResponse(BaseModel):
    tag: str
    color: str | None = None


class ProfileResponse(BaseModel):
    id: str
    name: str
    fingerprint_seed: int
    proxy: str | None = None
    proxy_id: str | None = None
    timezone: str | None = None
    locale: str | None = None
    platform: str = "windows"
    user_agent: str | None = None
    screen_width: int = 1920
    screen_height: int = 1080
    gpu_vendor: str | None = None
    gpu_renderer: str | None = None
    hardware_concurrency: int | None = None
    humanize: bool = False
    human_preset: str = "default"
    headless: bool = False
    geoip: bool = False
    clipboard_sync: bool = True
    auto_launch: bool = False

    @field_validator("clipboard_sync", mode="before")
    @classmethod
    def coerce_clipboard_sync(cls, v: object) -> bool:
        return v if v is not None else True

    color_scheme: str | None = None
    launch_args: list[str] = []
    notes: str | None = None
    region: str | None = None
    browser_type: str = "chromium"
    user_data_dir: str
    created_at: str
    updated_at: str
    tags: list[TagResponse] = []
    status: str = "stopped"  # "running" | "stopped"
    vnc_ws_port: int | None = None
    cdp_url: str | None = None


class LaunchResponse(BaseModel):
    profile_id: str
    status: str = "running"
    vnc_ws_port: int
    display: str
    cdp_url: str | None = None


class StatusResponse(BaseModel):
    running_count: int
    binary_version: str
    profiles_total: int


class ProfileStatusResponse(BaseModel):
    status: str  # "running" | "stopped"
    vnc_ws_port: int | None = None
    display: str | None = None
    cdp_url: str | None = None


class ClipboardRequest(BaseModel):
    text: str = Field(max_length=1_048_576)  # 1MB max


class LoginRequest(BaseModel):
    token: str


# ---------------------------------------------------------------------------
# Phase 1 auth/RBAC models.
#
# These describe the multi-tenant data shape defined in
# ``docs/ARCHITECTURE`` §2.2 / §2.3 and surface rows produced by
# ``backend/db_auth.py``. They are intentionally not yet wired into any router;
# the API layer will adopt them in Wave 2 (which is also when the legacy
# token-based ``LoginRequest`` above is expected to be retired in favour of
# ``EmailLoginRequest`` below).
# ---------------------------------------------------------------------------


class Tenant(BaseModel):
    id: str
    name: str
    plan_id: str = "free"
    status: str = "active"
    created_at: str


class UserPublic(BaseModel):
    """A user row safe to serialise to clients — never includes ``password_hash``.

    ``email_verified_at`` is an ISO-formatted timestamp when the user has
    completed the email verification flow (``POST /api/auth/verify-email``),
    or ``None`` otherwise. The SPA uses it to decide whether to render the
    "please verify your email" banner.
    """

    id: str
    tenant_id: str
    email: EmailStr
    status: str = "active"
    created_at: str
    email_verified_at: str | None = None


class Workspace(BaseModel):
    id: str
    tenant_id: str
    name: str
    owner_user_id: str
    created_at: str


class WorkspaceMember(BaseModel):
    workspace_id: str
    user_id: str
    role: Literal["owner", "admin", "editor", "launcher", "viewer"]


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class WorkspaceMemberPublic(BaseModel):
    """A workspace_members row joined with the user's email."""

    user_id: str
    email: EmailStr
    role: Literal["owner", "admin", "editor", "launcher", "viewer"]
    created_at: str


class WorkspaceWithMembers(BaseModel):
    """A workspace plus its full member list — used by the detail endpoint."""

    id: str
    tenant_id: str
    name: str
    owner_user_id: str
    created_at: str
    members: list[WorkspaceMemberPublic] = []


class InviteMemberRequest(BaseModel):
    email: EmailStr
    role: Literal["owner", "admin", "editor", "launcher", "viewer"]


class UpdateMemberRoleRequest(BaseModel):
    role: Literal["owner", "admin", "editor", "launcher", "viewer"]


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    tenant_name: str | None = None


class EmailLoginRequest(BaseModel):
    """Email + password login payload.

    Named distinctly from the legacy token-based ``LoginRequest`` so that both
    can coexist while Wave 2 migrates the auth router.

    ``code`` is the optional TOTP code, supplied on the second leg of an MFA
    login challenge. Absent for users without MFA enabled, or for the first
    request from an MFA user (server responds with ``{mfa_required: true}``).
    """

    email: EmailStr
    password: str
    code: str | None = None


class MfaSetupResponse(BaseModel):
    """Returned from ``POST /api/auth/mfa/setup``.

    The ``secret`` is NOT yet persisted — the client must echo it back to
    ``/mfa/enable`` together with a valid TOTP code to confirm enrolment.
    """

    secret: str
    qr_provisioning_uri: str


class MfaEnableRequest(BaseModel):
    secret: str
    code: str


class MfaDisableRequest(BaseModel):
    password: str
    code: str


class ApiKeyCreate(BaseModel):
    name: str
    scopes: list[str] | None = None


class ApiKeyPublic(BaseModel):
    """API key row safe to serialise to clients — never includes ``key_hash``."""

    id: str
    name: str
    scopes: list[str]
    last_used_at: str | None = None
    created_at: str


class AuditLog(BaseModel):
    """One row from ``audit_logs`` — the immutable trace of a mutation.

    Surfaces rows produced by :mod:`backend.db_audit`. See
    ``docs/ARCHITECTURE`` §2.2 and §2.9.
    """

    id: str
    tenant_id: str | None
    actor_user_id: str | None
    action: str
    resource_type: str | None
    resource_id: str | None
    ip: str | None
    user_agent: str | None
    status: str
    payload: dict | None
    ts: datetime


# ---------------------------------------------------------------------------
# Phase 2 proxy pool models.
#
# Surface for the workspace-level proxy pool from
# ``docs/ARCHITECTURE`` §2.5; rows produced by :mod:`backend.db_proxy`. As
# with the auth models above, these are intentionally not yet wired into
# any router — the proxy CRUD routes / browser_manager adoption land in a
# later Phase 2 task. ``password_enc`` is deliberately absent from
# :class:`Proxy` so it can never be serialised to clients.
# ---------------------------------------------------------------------------


ProxyType = Literal["http", "https", "socks5"]
ProxyStatus = Literal["ok", "fail", "unchecked"]


class Proxy(BaseModel):
    """A proxy row safe to serialise to clients — never includes credentials."""

    id: str
    workspace_id: str
    name: str
    type: ProxyType
    host: str
    port: int
    username: str | None = None
    provider: str | None = None
    rotation_url: str | None = None
    sticky_session: str | None = None
    country_code: str | None = None
    status: ProxyStatus = "unchecked"
    latency_ms: int | None = None
    last_check_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime


class ProxyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: ProxyType
    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    username: str | None = None
    password: str | None = None  # plaintext IN; encrypted before persistence
    provider: str = "manual"
    rotation_url: str | None = None
    sticky_session: str | None = None


class ProxyUpdate(BaseModel):
    name: str | None = None
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = None
    password: str | None = None  # plaintext IN; encrypted before persistence
    rotation_url: str | None = None
    sticky_session: str | None = None
    country_code: str | None = None


class ProxyBulkCreate(BaseModel):
    """Payload for ``POST /api/proxies/bulk``.

    Capped at 500 entries per request — anything larger should be split by
    the client. Each entry is validated independently as a :class:`ProxyCreate`
    so per-row errors can be surfaced without rejecting the whole batch.
    """

    proxies: list[ProxyCreate] = Field(min_length=1, max_length=500)


class ProxyBulkResult(BaseModel):
    """Per-row outcome of a bulk import call.

    ``failed`` is a list of ``{index, error}`` records pointing back at the
    request payload, so the client can highlight problematic rows in its
    paste/import dialog. ``proxies`` contains only the successfully inserted
    rows (already sanitised, no ``password_enc``).
    """

    created: int
    failed: list[dict]
    proxies: list[Proxy]


# ---------------------------------------------------------------------------
# Phase 4 Automation / RPA models.
#
# Surface for the four automation tables from ``docs/ARCHITECTURE`` §2.6;
# rows produced by :mod:`backend.db_automation`. Not yet wired into any
# router or engine — the interpreter / scheduler / worker land in
# follow-up Phase 4 tasks. ``Literal`` enums mirror the frozensets in
# ``db_automation`` so a router using these models gets the same
# validation envelope the data layer enforces.
# ---------------------------------------------------------------------------


AutomationKind = Literal["flow", "script"]
AutomationScriptLanguage = Literal["typescript", "python"]
AutomationRunStatus = Literal[
    "queued", "running", "success", "failure", "cancelled"
]
AutomationTrigger = Literal["manual", "schedule", "webhook", "api"]


class Automation(BaseModel):
    id: str
    workspace_id: str
    name: str
    description: str | None = None
    kind: AutomationKind
    latest_version_id: str | None = None
    created_at: datetime
    updated_at: datetime


class AutomationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: AutomationKind
    description: str | None = None


class AutomationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None


class AutomationVersion(BaseModel):
    id: str
    automation_id: str
    version: int
    kind: AutomationKind
    dsl_json: dict | None = None
    script_language: AutomationScriptLanguage | None = None
    script_code: str | None = None
    created_at: datetime
    created_by_user_id: str | None = None


class AutomationVersionCreate(BaseModel):
    """Payload to publish a new version of an automation.

    ``kind`` is inherited from the parent automation server-side, so the
    payload doesn't repeat it. The server validates that exactly the right
    sub-fields are populated for the kind (DSL for flow, code+language for
    script) in the data layer / router.
    """

    dsl_json: dict | None = None
    script_language: AutomationScriptLanguage | None = None
    script_code: str | None = None


class AutomationRun(BaseModel):
    id: str
    automation_version_id: str
    profile_id: str | None = None
    status: AutomationRunStatus
    started_at: datetime
    ended_at: datetime | None = None
    log_text: str | None = None
    result_json: dict | None = None
    error_message: str | None = None
    triggered_by: AutomationTrigger
    triggered_by_user_id: str | None = None


class AutomationRunCreate(BaseModel):
    """Payload to enqueue a manual run from the UI / API."""

    profile_id: str | None = None


class Schedule(BaseModel):
    id: str
    automation_id: str
    profile_id: str | None = None
    cron: str
    timezone: str = "UTC"
    enabled: bool = True
    next_fire_at: datetime | None = None
    last_fire_at: datetime | None = None
    created_at: datetime


class ScheduleCreate(BaseModel):
    cron: str = Field(min_length=1)
    profile_id: str | None = None
    timezone: str = "UTC"
    enabled: bool = True


class ScheduleUpdate(BaseModel):
    cron: str | None = Field(default=None, min_length=1)
    enabled: bool | None = None
    timezone: str | None = None
    profile_id: str | None = None


# ---------------------------------------------------------------------------
# Email verification (Phase 1 closure — see ``backend/routers/auth.py``)
# ---------------------------------------------------------------------------


class ResendVerificationResponse(BaseModel):
    """Reply from ``POST /api/auth/resend-verification``.

    Exactly one of the two fields is set: ``already_verified`` short-circuits
    when the caller's account is already verified (no email is sent), while
    ``sent`` reports the outcome of the SMTP submission otherwise.
    """

    sent: bool | None = None
    already_verified: bool | None = None


# ---------------------------------------------------------------------------
# OAuth (Phase 1 task WW — Google + GitHub social login)
#
# These models surface the OAuth provider abstraction defined in
# :mod:`backend.oauth` to the public API. The data layer (``oauth_provider``
# / ``oauth_provider_user_id`` columns added in migration 0010) is not
# exposed directly — only the front-end-facing "is this provider configured?"
# status is, so the SPA can decide which social-login buttons to render.
# ---------------------------------------------------------------------------


OAuthProviderName = Literal["google", "github"]


class OAuthProvidersStatus(BaseModel):
    """Reply from ``GET /api/auth/oauth/providers``.

    Each field is ``True`` iff the matching pair of environment variables
    (``<PROVIDER>_OAUTH_CLIENT_ID`` + ``<PROVIDER>_OAUTH_CLIENT_SECRET``)
    are both set. The frontend hides the corresponding "Continue with X"
    button when the value is ``False`` so users don't see options that
    will fail at the ``/start`` step.
    """

    google: bool = False
    github: bool = False


# ---------------------------------------------------------------------------
# Phase 3 cloud-sync models.
#
# Surface for the ``profile_versions`` table from
# ``docs/ARCHITECTURE`` §2.7; rows produced by :mod:`backend.db_versions`.
# Not yet wired into any router or into ``browser_manager`` — the launch
# flow that creates snapshots lands in agent BBB's task and the REST
# surface lands in a later wave. ``storage_key`` is the opaque object key
# in S3 / MinIO / the local dev fallback (see :mod:`backend.storage`).
# ---------------------------------------------------------------------------


class ProfileVersion(BaseModel):
    """One snapshot row indexed by ``backend.db_versions``."""

    id: str
    profile_id: str
    version: int
    storage_key: str
    size_bytes: int | None = None
    sha256: str | None = None
    created_at: datetime
    created_by_user_id: str | None = None
    created_by_session_id: str | None = None
    notes: str | None = None


class RestoreResponse(BaseModel):
    """Reply from ``POST /api/profiles/{id}/versions/{version_id}/restore``."""

    restored: bool
    version: int


class PresignedUrlResponse(BaseModel):
    """Reply from ``GET /api/profiles/{id}/versions/{version_id}/download``.

    ``url`` is a short-lived signed download URL when the backend is S3-
    compatible; for the LocalBackend it's a ``file://`` URL (see
    :mod:`backend.storage`).
    """

    url: str
    expires_in: int
    storage_key: str
    size_bytes: int | None = None


# ---------------------------------------------------------------------------
# Phase 3 wave 2 (task GGG) — region selector models.
#
# Backs ``GET /api/regions`` and the workspace/profile ``region`` fields. See
# :mod:`backend.regions` for the source of truth on which region codes are
# configured at runtime (via the ``WORKER_REGIONS`` env var).
# ---------------------------------------------------------------------------


class Region(BaseModel):
    code: str
    label: str
    available: bool = True


class RegionList(BaseModel):
    regions: list[Region]
    default: str


# ---------------------------------------------------------------------------
# Phase 5 wave 1 (task HHH) — billing & metering models.
#
# Backs the plan catalogue (``GET /api/plans``), the tenant subscription
# view, and the quota dashboard described in ``docs/ARCHITECTURE`` §2.8.
# The actual REST surface and Stripe/VNPay wiring land in later Phase 5
# waves; these schemas are introduced now alongside
# :mod:`backend.db_billing` so router code can import the types directly
# without reaching into the DB layer for shape.
#
# ``None`` on any ``max_*`` field means "unlimited" — same convention as
# the underlying ``plans`` table columns.
# ---------------------------------------------------------------------------


class Plan(BaseModel):
    id: str
    name: str
    description: str | None = None
    price_cents: int
    interval: str
    max_profiles: int | None = None
    max_concurrent_runs: int | None = None
    max_workspace_members: int | None = None
    max_automation_minutes: int | None = None
    max_storage_gb: int | None = None
    allow_regions: list[str]
    is_public: bool
    sort_order: int


class Subscription(BaseModel):
    id: str
    tenant_id: str
    plan_id: str
    status: str
    payment_provider: str | None = None
    provider_subscription_id: str | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool
    trial_end: datetime | None = None
    created_at: datetime


class UsageCounter(BaseModel):
    id: str
    tenant_id: str
    period_start: date
    period_end: date
    profile_count: int
    concurrent_runs_peak: int
    automation_minutes_used: int
    storage_gb_used: float
    workspace_members_count: int
    updated_at: datetime


class TenantQuotaResponse(BaseModel):
    """Composite payload for the per-tenant quota dashboard endpoint.

    ``at_limit`` is a flat ``{resource: bool}`` map computed by the
    quota helper so the frontend can render badge / lock-out UI without
    re-deriving the comparison client-side. Keys are stable resource
    slugs (e.g. ``'profiles'``, ``'concurrent_runs'``,
    ``'automation_minutes'``, ``'workspace_members'``, ``'storage_gb'``).
    """

    plan: Plan
    subscription: Subscription | None = None
    usage: UsageCounter
    at_limit: dict[str, bool]


class Invoice(BaseModel):
    """One payment-provider invoice stored under ``invoices``.

    Phase 5 closure — populated by the Stripe webhook (invoice.*) and
    surfaced in the Billing tab so a tenant can audit charges + grab
    the provider's PDF.
    """

    id: str
    tenant_id: str
    subscription_id: str | None = None
    provider: str
    provider_invoice_id: str
    number: str | None = None
    amount_cents: int
    currency: str
    status: str
    hosted_invoice_url: str | None = None
    invoice_pdf_url: str | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    paid_at: datetime | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# AI assistant (Phase 6, task QQQ)
# ---------------------------------------------------------------------------


class AiBuildRequest(BaseModel):
    """Request body for ``POST /api/ai/build-automation``."""

    prompt: str = Field(min_length=5, max_length=4000)


class AiBuildResponse(BaseModel):
    """Generated DSL flow plus a flag indicating whether the real LLM ran.

    ``configured=False`` means no ``ANTHROPIC_API_KEY`` was set on the
    server so the response is a templated dev-mode placeholder — the
    frontend surfaces this as a warning banner.
    """

    dsl: dict
    configured: bool


# ── Marketplace (Phase 6 task PPP) ───────────────────────────────────────────
#
# Public catalog + per-workspace install ledger. Schema lives in migration
# ``0018_add_marketplace``; data layer in :mod:`backend.db_marketplace`;
# HTTP routes in :mod:`backend.routers.marketplace`. See
# ``docs/ARCHITECTURE`` §2.6 for the broader marketplace design (GemStore
# / GPM-style automation app store).


class MarketplaceApp(BaseModel):
    """One row of the public ``marketplace_apps`` catalog.

    ``dsl_json`` / ``script_code`` are intentionally omitted from the
    list-payload schema — clients fetch the full row via
    ``GET /api/marketplace/apps/{id}`` once the user clicks install.
    """

    id: str
    slug: str
    name: str
    description: str | None = None
    long_description: str | None = None
    icon_url: str | None = None
    category: str | None = None
    kind: str
    version: str
    creator_name: str | None = None
    creator_url: str | None = None
    install_count: int
    is_official: bool
    is_public: bool
    required_permissions: list[str]
    created_at: datetime
    updated_at: datetime


class InstallRequest(BaseModel):
    """Body of ``POST /api/marketplace/apps/{id}/install``.

    ``workspace_id`` is optional — the router falls back to the caller's
    oldest workspace when missing.
    """

    workspace_id: str | None = None


class TenantAppInstall(BaseModel):
    """One row of ``tenant_app_installs``.

    Pinned to a workspace (not just a tenant) so seat-scoped installs
    are possible in later phases. ``automation_id`` is nullable because
    the FK is ``ON DELETE SET NULL`` — the user deleting their cloned
    automation should not break the marketplace UI.
    """

    id: str
    tenant_id: str
    workspace_id: str
    app_id: str
    automation_id: str | None = None
    installed_at: datetime
    app_version: str | None = None


class MarketplaceAppSubmit(BaseModel):
    """Body of ``POST /api/marketplace/apps/submit`` (Phase 6 phase 2).

    Validated server-side: the router additionally enforces slug
    alphanumeric+dash, slug uniqueness, and (for ``kind='flow'``) the
    presence of a parseable ``dsl_json`` with at least a ``nodes`` array.
    """

    slug: str = Field(min_length=3, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    long_description: str | None = None
    category: str | None = None
    kind: Literal["flow", "script"]
    dsl_json: dict | None = None
    script_language: str | None = None
    script_code: str | None = None
    icon_url: str | None = None
    creator_name: str | None = None
    creator_url: str | None = None


# ---------------------------------------------------------------------------
# Phase 7 phase 1 — overage billing.
#
# One row per "we let the tenant exceed the per-period cap" decision,
# persisted by :func:`backend.db_billing.record_overage_event`. The
# local ledger is the source of truth: even if Stripe is unreachable
# at event time, the row lands here and the phase-2 daily reconciler
# replays unreported events (``stripe_usage_record_id IS NULL``).
# ---------------------------------------------------------------------------


class OverageEvent(BaseModel):
    """One ``overage_events`` row.

    ``unit_price_cents`` is a snapshot of the plan price at event time
    so re-pricing the plan later cannot retroactively change historical
    bills. ``stripe_usage_record_id`` is ``None`` until the reconciler
    successfully relays the event to Stripe's metered API.
    """

    id: str
    tenant_id: str
    subscription_id: str | None = None
    resource: str
    units: int
    unit_price_cents: int | None = None
    stripe_usage_record_id: str | None = None
    occurred_at: datetime
    period_start: date
    period_end: date
