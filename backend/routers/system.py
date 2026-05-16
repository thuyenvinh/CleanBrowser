"""System-level endpoints (status / healthcheck)."""

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
