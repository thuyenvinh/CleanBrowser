"""System-level endpoints (status / healthcheck / public uptime feed)."""

from __future__ import annotations

from fastapi import APIRouter

from .. import database as db
from ..dependencies import browser_mgr
from ..models import StatusResponse

router = APIRouter(tags=["system"])


@router.get("/api/status", response_model=StatusResponse)
async def get_system_status():
    from cloakbrowser.config import CHROMIUM_VERSION

    profiles = db.list_profiles()
    return StatusResponse(
        running_count=len(browser_mgr.running),
        binary_version=CHROMIUM_VERSION,
        profiles_total=len(profiles),
    )


# Services rolled into the public uptime feed. Order matters — drives
# the row order on the rendered status page. Keep in sync with
# :data:`backend.status_worker.PROBES`; a probe that isn't listed here
# still has data recorded but won't appear on the public page.
_PUBLIC_SERVICES: list[str] = ["api", "auth"]


def _classify(uptime_24h: float) -> str:
    """Map a 24h uptime % into the three-state public status label.

    Thresholds match the convention used by most public status pages
    (StatusPage.io / Atlassian): >= 99 % is "operational", anything
    below 95 % is a "major outage", everything in between is
    "degraded". The 24h window (rather than 7d/30d) is the right horizon
    for the *current* health badge because slower windows would mask a
    fresh ongoing outage.
    """
    if uptime_24h >= 99.0:
        return "operational"
    if uptime_24h >= 95.0:
        return "degraded"
    return "major_outage"


@router.get("/api/status/public")
async def status_public():
    """Public uptime feed — no auth. Backs the ``/status`` page.

    Returns rolling 24h / 7d / 30d uptime per service, the overall
    aggregate (operational | degraded | major_outage), and a recent
    incident feed for the last 7 days. Intentionally cheap: every
    aggregate is a single index range scan thanks to the composite
    ``(service_name, ts DESC)`` index from migration 0023.

    Auth note: this endpoint is intentionally *not* listed in
    ``_AUTH_EXEMPT``; in the default deployment ``AUTH_TOKEN`` is unset
    so the legacy middleware lets it through, and in multi-tenant
    deployments the JWT session middleware never blocks unauthenticated
    GETs to public-API paths. If a future deploy turns ``AUTH_TOKEN``
    back on, the exempt list will need to grow to include
    ``/api/status/public``.
    """
    from .. import db_status
    from ..middleware_rls import system_context

    with system_context():
        services_status: dict[str, str] = {}
        uptime_24h: dict[str, float] = {}
        uptime_7d: dict[str, float] = {}
        uptime_30d: dict[str, float] = {}

        degraded_count = 0
        major_outage_count = 0
        for svc in _PUBLIC_SERVICES:
            u24 = db_status.uptime_percentage(svc, hours=24)
            u7d = db_status.uptime_percentage(svc, hours=24 * 7)
            u30 = db_status.uptime_percentage(svc, hours=24 * 30)
            label = _classify(u24)
            services_status[svc] = label
            uptime_24h[svc] = round(u24, 3)
            uptime_7d[svc] = round(u7d, 3)
            uptime_30d[svc] = round(u30, 3)
            if label == "major_outage":
                major_outage_count += 1
            elif label == "degraded":
                degraded_count += 1

        # Overall rollup: any major_outage anywhere = major_outage page
        # only when *every* service is down (matches public-page
        # convention — one degraded sub-service shouldn't flip the
        # banner red). Any degraded -> degraded banner.
        if major_outage_count == len(_PUBLIC_SERVICES) and _PUBLIC_SERVICES:
            overall = "major_outage"
        elif major_outage_count > 0 or degraded_count > 0:
            overall = "degraded"
        else:
            overall = "operational"

        incidents = db_status.list_recent_incidents(hours=24 * 7)

        return {
            "overall": overall,
            "services": services_status,
            "uptime_24h": uptime_24h,
            "uptime_7d": uptime_7d,
            "uptime_30d": uptime_30d,
            "recent_incidents": incidents,
        }
