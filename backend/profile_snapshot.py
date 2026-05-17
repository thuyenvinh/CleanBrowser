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


async def snapshot_to_storage_diff(
    profile_id: str,
    user_data_dir: str | Path,
    tenant_id: str,
    session_id: str | None = None,
    user_id: str | None = None,
    notes: str | None = None,
    full_every: int = 10,
) -> dict[str, Any] | None:
    """Diff-aware snapshot — uploads only files changed since the parent.

    Falls back to a full snapshot in any of these cases:

    * No previous version exists for the profile (cold start).
    * The chain of diffs back to the nearest full is already
      ``full_every`` long. Bounding the chain keeps restore latency
      predictable (otherwise a long-lived profile would accumulate
      hundreds of diffs and replay would dominate the launch time).
    * The previous version exists but has no recorded file metadata
      (e.g. it was a full snapshot from before migration 0021). We can't
      compute a meaningful diff against an unknown manifest, so we take
      a fresh full and the next snapshot can diff from there.

    Returns the freshly-created ``profile_versions`` row dict on success,
    ``None`` if any step failed OR if there was nothing to snapshot
    (no files changed since the parent — a no-op is reported as None
    so callers can distinguish "saved a snapshot" from "nothing to do").
    """

    import json

    from backend import db_versions, snapshot_diff, storage

    udir = Path(user_data_dir)
    if not udir.exists():
        logger.warning(
            "snapshot_diff: user_data_dir missing for %s (%s)",
            profile_id, udir,
        )
        return None

    loop = asyncio.get_event_loop()

    # Decide full vs diff up front so we only do the cheap DB lookups
    # before the expensive walk/hash phase.
    try:
        parent = db_versions.get_latest_version(profile_id)
    except Exception:
        logger.exception(
            "snapshot_diff: get_latest_version failed for %s", profile_id
        )
        return None

    use_full = parent is None
    prev_files_meta: list[dict] = []
    if parent and not use_full:
        # Chain-depth check: walk back via the helper added in 0021. If
        # the nearest full is too far away, force a fresh full so restore
        # doesn't accumulate unbounded replay work.
        try:
            full_ancestor = db_versions.find_full_snapshot_before(parent["id"])
        except Exception:
            logger.exception(
                "snapshot_diff: chain walk failed for %s", profile_id
            )
            return None
        if full_ancestor is None:
            # Broken chain — safest path is a fresh full snapshot.
            use_full = True
        else:
            # Count how many diffs sit between ``parent`` (inclusive) and
            # the full ancestor. parent itself counts as a hop only when
            # it's a diff; if parent IS the full, depth is 0 and we
            # should diff against it on the next snapshot.
            depth = 0
            cur = parent
            while cur and cur.get("id") != full_ancestor.get("id"):
                depth += 1
                pid = cur.get("parent_version_id")
                cur = db_versions.get_version(pid) if pid else None
                if depth > 50:
                    break
            if depth >= full_every:
                use_full = True
            else:
                try:
                    prev_files_meta = db_versions.get_version_files(
                        parent["id"]
                    )
                except Exception:
                    logger.exception(
                        "snapshot_diff: get_version_files failed for %s",
                        parent["id"],
                    )
                    return None
                if not prev_files_meta:
                    # Parent predates the per-file manifest — can't diff.
                    use_full = True

    if use_full:
        # Reuse the existing full-snapshot path but ALSO record the
        # per-file manifest so the *next* call can diff against this
        # full. Without that, the diff flow would degenerate to "always
        # take a full" on profiles whose first snapshot was full.
        row = await snapshot_to_storage(
            profile_id=profile_id,
            user_data_dir=str(udir),
            tenant_id=tenant_id,
            session_id=session_id,
            user_id=user_id,
            notes=notes,
        )
        if row is None:
            return None
        try:
            current = await loop.run_in_executor(
                None, snapshot_diff._walk_user_data, udir
            )
            files_meta = {
                p: {"sha256": sha, "size": size}
                for p, (sha, size) in current.items()
            }
            db_versions.record_version_files(row["id"], files_meta)
        except Exception:
            # Recording the manifest is best-effort: if it fails the
            # full snapshot itself is still valid, the next call will
            # just have to take another full instead of a diff.
            logger.exception(
                "snapshot_diff: record_version_files failed for full %s",
                row.get("id"),
            )
        return row

    # --- diff path ---
    prev_files_sha = {row["path"]: row["sha256"] for row in prev_files_meta}

    try:
        compressed, manifest, changed = await loop.run_in_executor(
            None, snapshot_diff.pack_diff, udir, prev_files_sha,
        )
    except Exception:
        logger.exception("snapshot_diff: pack_diff failed for %s", profile_id)
        return None

    if not changed:
        logger.info(
            "snapshot_diff: no changes since v%s for profile %s — skipping",
            parent["version"], profile_id,
        )
        return None

    next_version = parent["version"] + 1
    # Storage layout: parallel to the v{n}.tar.zst full keys but with a
    # ``.diff`` infix so a glance at the bucket tells full vs diff. The
    # manifest rides alongside under ``.manifest.json`` for offline
    # debugging / out-of-band inspection (the DB is still authoritative).
    base_key = storage.make_profile_snapshot_key(
        tenant_id, profile_id, next_version
    )
    diff_key = base_key.replace(".tar.zst", ".diff.tar.zst")
    manifest_key = base_key.replace(".tar.zst", ".manifest.json")

    sha = hashlib.sha256(compressed).hexdigest()
    try:
        storage.upload(diff_key, compressed)
        storage.upload(manifest_key, json.dumps(manifest).encode())
    except Exception:
        logger.exception(
            "snapshot_diff: upload failed for %s key=%s", profile_id, diff_key
        )
        return None

    try:
        version_row = db_versions.create_version(
            profile_id=profile_id,
            storage_key=diff_key,
            size_bytes=len(compressed),
            sha256=sha,
            created_by_user_id=user_id,
            created_by_session_id=session_id,
            notes=notes,
        )
        db_versions.mark_diff(version_row["id"], parent_id=parent["id"])
        # Record the FULL current file map (not just ``changed``) so the
        # next diff knows the complete state without walking the chain.
        db_versions.record_version_files(version_row["id"], manifest["files"])
    except Exception:
        logger.exception("snapshot_diff: db record failed for %s", profile_id)
        # Best-effort cleanup of both orphaned objects.
        for k in (diff_key, manifest_key):
            try:
                storage.delete(k)
            except Exception:
                logger.debug("snapshot_diff: orphan cleanup failed for %s", k)
        return None

    logger.info(
        "snapshot_diff: profile %s v%s saved (%d bytes, %d/%d files changed)",
        profile_id, version_row.get("version"),
        len(compressed), len(changed), len(manifest["files"]),
    )
    return version_row


async def restore_from_storage_diff(
    profile_id: str,
    version_id: str | None,
    user_data_dir: str | Path,
) -> bool:
    """Restore a profile by replaying full+diff chain into ``user_data_dir``.

    Walks back from ``version_id`` (or latest) until it hits a full
    snapshot, then applies each diff in ancestor→descendant order onto
    a freshly-emptied ``user_data_dir``. Returns ``True`` on success,
    ``False`` if any download/unpack step failed or if the chain is
    broken (an ancestor's ``parent_version_id`` is NULL but its kind is
    still ``'diff'``).
    """

    import shutil

    from backend import db_versions, snapshot_diff, storage

    try:
        if version_id:
            target = db_versions.get_version(version_id)
        else:
            target = db_versions.get_latest_version(profile_id)
    except Exception:
        logger.exception(
            "restore_diff: lookup failed for %s version=%s",
            profile_id, version_id,
        )
        return False
    if not target:
        logger.warning(
            "restore_diff: no version found for %s (version_id=%s)",
            profile_id, version_id,
        )
        return False

    # Build the chain by walking parent pointers back to the nearest full.
    chain: list[dict] = []
    cur = target
    while cur is not None:
        chain.append(cur)
        if cur.get("snapshot_kind", "full") == "full":
            break
        parent_id = cur.get("parent_version_id")
        if not parent_id:
            logger.error(
                "restore_diff: broken chain — version %s is a diff with no "
                "parent_version_id",
                cur.get("id"),
            )
            return False
        try:
            cur = db_versions.get_version(parent_id)
        except Exception:
            logger.exception(
                "restore_diff: parent lookup failed for %s", parent_id
            )
            return False
        if cur is None:
            logger.error(
                "restore_diff: broken chain — parent %s missing", parent_id
            )
            return False
        if len(chain) > 100:
            # Same safety bound as the chain-depth helper.
            logger.error(
                "restore_diff: chain too deep for %s, aborting", profile_id
            )
            return False
    chain.reverse()  # ancestor (full) → descendant (target)

    udir = Path(user_data_dir)
    loop = asyncio.get_event_loop()

    # Wipe target dir for clean full-restore semantics. The diff stream
    # is overwrite-only, so without this a previous restore's files
    # could survive into a snapshot they were never part of.
    if udir.exists():
        try:
            shutil.rmtree(udir)
        except Exception:
            logger.exception(
                "restore_diff: wipe failed for %s", udir
            )
            return False
    udir.mkdir(parents=True, exist_ok=True)

    for v in chain:
        key = v.get("storage_key")
        try:
            data = storage.download(key)
        except Exception:
            logger.exception(
                "restore_diff: download failed key=%s", key
            )
            return False
        try:
            if v.get("snapshot_kind", "full") == "full":
                await loop.run_in_executor(None, unpack, data, str(udir))
            else:
                await loop.run_in_executor(
                    None, snapshot_diff.unpack_diff, data, udir
                )
        except Exception:
            logger.exception(
                "restore_diff: unpack failed at version %s", v.get("id")
            )
            return False

    logger.info(
        "restore_diff: profile %s restored via %d-link chain (target v%s)",
        profile_id, len(chain), target.get("version"),
    )
    return True


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
