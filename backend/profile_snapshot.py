"""Snapshot user_data_dir to S3 storage as tar+zstd, restore on demand.

Phase 3 wave 1 (task BBB) — packs a profile's ``user_data_dir`` into a
single compressed blob and uploads it via ``backend.storage`` so the
matching ``profile_versions`` row (created via ``backend.db_versions``)
points at recoverable bytes. The browser_manager calls
``snapshot_to_storage`` after every clean stop / browser close so the
latest profile state is always durable in cloud storage.

Restore is intentionally NOT wired into ``launch`` yet — that's a later
wave once the explicit "restore from version X" API surface lands. The
function is exposed so that endpoint can call it without re-implementing
the unpack logic.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import tarfile
from pathlib import Path
from typing import Any

import zstandard as zstd

logger = logging.getLogger(__name__)

# zstd level 3 is the library default — fast enough for synchronous
# call-sites yet still ~3x denser than uncompressed tar for Chromium
# profiles. Bumping past ~6 hits diminishing returns on profile data
# (lots of already-compressed PNG/woff blobs in the cache).
COMPRESS_LEVEL = 3


def pack(user_data_dir: str | Path) -> tuple[bytes, str, int]:
    """Tar + zstd-compress ``user_data_dir``.

    Returns ``(compressed_bytes, sha256_hex_of_compressed, size_bytes)``.

    Raises ``FileNotFoundError`` if the directory does not exist — this
    is treated as a soft error by the snapshot wrapper (e.g. profile
    deleted before stop callback fired).
    """
    udir = Path(user_data_dir)
    if not udir.exists():
        raise FileNotFoundError(udir)

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        # Skip lock files and on-disk caches: they're either Chromium
        # singletons that must NOT be restored on another host (they
        # encode a PID + hostname) or large/regenerable blobs that
        # would balloon the snapshot for no functional gain.
        def _filt(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo | None:
            name = tarinfo.name
            lower = name.lower()
            base = lower.rsplit("/", 1)[-1]
            if base in ("singletonlock", "singletoncookie", "singletonsocket"):
                return None
            # Match "Cache", "Code Cache", "GPUCache" anywhere in path.
            parts = lower.split("/")
            if any(p.endswith("cache") or p == "cache" for p in parts):
                return None
            return tarinfo

        tf.add(str(udir), arcname=".", filter=_filt)

    raw = buf.getvalue()
    cctx = zstd.ZstdCompressor(level=COMPRESS_LEVEL)
    compressed = cctx.compress(raw)
    sha = hashlib.sha256(compressed).hexdigest()
    return compressed, sha, len(compressed)


def unpack(compressed: bytes, target_dir: str | Path) -> None:
    """Decompress + extract a snapshot to ``target_dir``.

    The directory is created if missing. Uses tarfile's ``filter='data'``
    on Python 3.12+ for path-traversal safety; on older runtimes falls
    back to a manual prefix check.
    """
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    dctx = zstd.ZstdDecompressor()
    raw = dctx.decompress(compressed)
    buf = io.BytesIO(raw)
    with tarfile.open(fileobj=buf, mode="r") as tf:
        try:
            tf.extractall(str(target), filter="data")
        except TypeError:
            # Python <3.12 — manually reject absolute / parent-traversal
            # entries before extracting.
            safe_members: list[tarfile.TarInfo] = []
            for member in tf.getmembers():
                if member.name.startswith("/"):
                    logger.warning("unpack: skipping absolute path %s", member.name)
                    continue
                if ".." in member.name.split("/"):
                    logger.warning("unpack: skipping traversal %s", member.name)
                    continue
                safe_members.append(member)
            tf.extractall(str(target), members=safe_members)


async def snapshot_to_storage(
    profile_id: str,
    user_data_dir: str | Path,
    tenant_id: str,
    session_id: str | None = None,
    user_id: str | None = None,
    notes: str | None = None,
) -> dict[str, Any] | None:
    """Pack + upload + record a snapshot for ``profile_id``.

    Returns the freshly-created ``profile_versions`` row dict on success
    or ``None`` if any step (pack / upload / db) fails. All failure
    modes are logged with ``exception()``; callers should treat ``None``
    as "snapshot didn't happen, carry on" rather than fatal.
    """
    from backend import db_versions, storage

    loop = asyncio.get_event_loop()
    try:
        data, sha, size = await loop.run_in_executor(None, pack, user_data_dir)
    except FileNotFoundError:
        logger.warning(
            "snapshot: user_data_dir missing for %s (%s)", profile_id, user_data_dir
        )
        return None
    except Exception:
        logger.exception("snapshot: pack failed for %s", profile_id)
        return None

    # Compute the next version number BEFORE upload so the storage key
    # encodes the correct slot. db_versions.create_version is
    # responsible for re-validating monotonicity under contention.
    try:
        latest = db_versions.get_latest_version(profile_id)
    except Exception:
        logger.exception("snapshot: get_latest_version failed for %s", profile_id)
        return None
    next_version = (latest["version"] + 1) if latest else 1

    key = storage.make_profile_snapshot_key(tenant_id, profile_id, next_version)

    try:
        storage.upload(key, data)
    except Exception:
        logger.exception(
            "snapshot: upload failed for %s key=%s", profile_id, key
        )
        return None

    try:
        version_row = db_versions.create_version(
            profile_id=profile_id,
            storage_key=key,
            size_bytes=size,
            sha256=sha,
            created_by_user_id=user_id,
            created_by_session_id=session_id,
            notes=notes,
        )
    except Exception:
        logger.exception("snapshot: db record failed for %s", profile_id)
        # Best-effort cleanup of the orphaned object so the bucket
        # doesn't grow unbounded on persistent DB failures.
        try:
            storage.delete(key)
        except Exception:
            logger.debug("snapshot: orphan cleanup failed for %s", key)
        return None

    logger.info(
        "snapshot: profile %s version %s saved (%d bytes, sha=%s)",
        profile_id, version_row.get("version"), size, sha[:12],
    )
    return version_row


async def restore_from_storage(
    profile_id: str,
    version_id: str | None,
    user_data_dir: str | Path,
) -> bool:
    """Download + extract a snapshot into ``user_data_dir``.

    If ``version_id`` is ``None``, the latest version for the profile is
    used. Returns ``True`` on success, ``False`` on any failure (logged).
    """
    from backend import db_versions, storage

    try:
        if version_id:
            v = db_versions.get_version(version_id)
        else:
            v = db_versions.get_latest_version(profile_id)
    except Exception:
        logger.exception(
            "restore: lookup failed for %s version=%s", profile_id, version_id
        )
        return False
    if not v:
        logger.warning(
            "restore: no version found for %s (version_id=%s)",
            profile_id, version_id,
        )
        return False

    try:
        data = storage.download(v["storage_key"])
    except Exception:
        logger.exception("restore: download failed key=%s", v["storage_key"])
        return False

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, unpack, data, str(user_data_dir))
    except Exception:
        logger.exception("restore: unpack failed for %s", profile_id)
        return False
    return True
