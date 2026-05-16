"""Region listing endpoint.

Phase 3 wave 2 (task GGG) — surfaces the regions configured via the
``WORKER_REGIONS`` env var so the SPA's profile form can render a region
select. Auth-light: any authenticated user may call it (and unauthenticated
callers are tolerated for parity with the legacy AUTH_TOKEN deploy mode).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import regions as regions_module
from ..dependencies import get_optional_user
from ..models import RegionList

router = APIRouter(prefix="/api", tags=["regions"])


@router.get("/regions", response_model=RegionList)
def list_regions_route(_: dict | None = Depends(get_optional_user)):
    """Return the configured region pool plus the default region code."""
    regs = regions_module.list_regions()
    return {
        "regions": [
            {"code": r.code, "label": r.label, "available": r.available}
            for r in regs
        ],
        "default": regions_module.default_region(),
    }
