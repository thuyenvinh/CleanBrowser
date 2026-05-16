"""Pydantic models for profile CRUD operations."""

from __future__ import annotations

from datetime import datetime
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
    """A user row safe to serialise to clients — never includes ``password_hash``."""

    id: str
    tenant_id: str
    email: EmailStr
    status: str = "active"
    created_at: str


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
