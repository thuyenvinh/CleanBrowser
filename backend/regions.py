"""Region registry. Phase 3 phase 2: static list from env.

Future: query Worker pool for actually-online regions.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Region:
    code: str        # 'us', 'eu', 'sg', 'vn', 'local'
    label: str       # 'United States (Virginia)'
    available: bool = True


_KNOWN_LABELS = {
    'local': 'Local server',
    'us': 'United States',
    'us-east': 'US East',
    'us-west': 'US West',
    'eu': 'Europe',
    'eu-west': 'Europe (Frankfurt)',
    'sg': 'Singapore',
    'jp': 'Japan',
    'vn': 'Vietnam',
    'au': 'Australia',
}


def list_regions() -> list[Region]:
    configured = os.environ.get('WORKER_REGIONS', 'local').strip()
    codes = [c.strip() for c in configured.split(',') if c.strip()]
    if not codes:
        codes = ['local']
    result = []
    for c in codes:
        label = _KNOWN_LABELS.get(c, c.upper())
        result.append(Region(code=c, label=label, available=True))
    return result


def get_region(code: str) -> Region | None:
    for r in list_regions():
        if r.code == code:
            return r
    return None


def default_region() -> str:
    return list_regions()[0].code


def resolve_for_profile(
    profile_region: str | None, workspace_region: str | None
) -> str:
    """Pick the effective region. Falls back through profile → workspace → default."""
    for candidate in (profile_region, workspace_region):
        if candidate and get_region(candidate):
            return candidate
    return default_region()
