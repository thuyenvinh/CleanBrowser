"""File-level diff snapshot helpers.

Phase 8 wave 1 — companion to :mod:`backend.profile_snapshot`. Where the
older ``pack`` / ``unpack`` pair tars the whole ``user_data_dir`` every
stop (~80% wasted bandwidth on stable profiles), this module computes a
per-file SHA-256 manifest, packs only the files whose hash changed since
the previous snapshot, and lets the restore path replay a chain of diffs
on top of the most recent full snapshot.

Algorithm
=========

``pack_diff(udir, prev_files)``
    Walk ``udir`` (skipping the same cache/lock entries the full packer
    skips), hash every file, and build a tar of files whose SHA-256
    differs from ``prev_files`` (a ``{rel_path: sha256}`` dict captured
    from the previous version). Returns the compressed tar plus a
    manifest describing **the full current state**, so subsequent diffs
    only need the immediate parent's manifest — not the entire chain.

``unpack_diff(compressed, target_dir)``
    Extract a single diff blob over an existing tree (overwrite-only).
    Deletion handling is intentionally deferred to a later wave: V1
    leaves stale files in place if the user deletes something inside the
    profile. That's a tolerable trade-off because Chromium rarely
    deletes — it overwrites — and the cost of being wrong is "the
    restored profile has a leftover empty extension dir", not data loss.

Manifest shape
==============
::

    {
        "kind": "diff",
        "files": {
            "<rel_path>": {"sha256": "<hex>", "size": <bytes>},
            ...
        },
        "added_or_changed": ["<rel_path>", ...],
    }

``files`` is the FULL current state (used by the next diff's pack);
``added_or_changed`` is the subset actually carried in the tar (used by
debug tooling and for size accounting).
"""
from __future__ import annotations

import hashlib
import io
import logging
import os
import tarfile
from pathlib import Path

import zstandard as zstd

logger = logging.getLogger(__name__)

# Matches profile_snapshot.COMPRESS_LEVEL — chosen empirically: level 3
# is ~3x denser than uncompressed tar on Chromium profile blobs but
# fast enough not to stall the stop hook.
COMPRESS_LEVEL = 3

# Skip cache dirs that are large and regenerable. Matches the lower-case
# substring filter in profile_snapshot.pack so the diff manifest and the
# full snapshot agree on what's in scope.
_SKIP_DIRS = {"Cache", "Code Cache", "GPUCache", "Service Worker"}
# Chromium singleton files encode PID + hostname; restoring them on
# another worker would prevent that worker's Chromium from starting.
_SKIP_FILES = {"SingletonLock", "SingletonCookie", "SingletonSocket"}


def _hash_file(path: Path, chunk_size: int = 65536) -> tuple[str, int]:
    """Streaming SHA-256 + size of a single file.

    Chunked so we don't materialise multi-MB profile DBs in memory just
    to hash them. Returns ``(hex_digest, size_in_bytes)``.
    """
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def _walk_user_data(udir: Path) -> dict[str, tuple[str, int]]:
    """Return ``{rel_path: (sha256, size_bytes)}`` for every in-scope file.

    "In scope" matches the full-snapshot filter: cache dirs and Chromium
    singleton lock files are silently skipped. Unreadable files are
    logged at WARNING and dropped from the manifest rather than aborting
    the whole snapshot — losing one stray broken symlink shouldn't
    sabotage durability of the rest of the profile.
    """
    result: dict[str, tuple[str, int]] = {}
    for root, dirs, files in os.walk(udir):
        # Prune cache dirs in-place so os.walk doesn't descend into them.
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for name in files:
            if name in _SKIP_FILES:
                continue
            full = Path(root) / name
            try:
                rel = str(full.relative_to(udir))
            except ValueError:
                # ``relative_to`` raises if ``full`` somehow escapes
                # ``udir`` (symlink loop, race). Drop defensively.
                logger.warning("snapshot_diff: path escaped udir: %s", full)
                continue
            try:
                sha, size = _hash_file(full)
            except OSError as e:
                logger.warning(
                    "snapshot_diff: skip unreadable file %s: %s", rel, e
                )
                continue
            result[rel] = (sha, size)
    return result


def pack_diff(
    udir: Path, prev_files: dict[str, str]
) -> tuple[bytes, dict, list[str]]:
    """Build a diff tar+zstd against ``prev_files``.

    ``prev_files`` is the ``{rel_path: sha256}`` projection of the
    previous version's manifest. Any current-state file whose path is
    missing from that mapping (new file) or whose SHA-256 doesn't match
    (modified) is included in the tar; everything else is omitted on the
    assumption the previous snapshot already carries it.

    Returns ``(compressed_bytes, manifest, changed_paths)``. The manifest
    captures the FULL current state (not just the diff) so the *next*
    snapshot can diff against it in one DB query.
    """
    udir = Path(udir)
    current = _walk_user_data(udir)
    changed = [
        path
        for path, (sha, _size) in current.items()
        if prev_files.get(path) != sha
    ]

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for rel in changed:
            full = udir / rel
            # arcname=rel keeps paths relative on extract so unpack_diff
            # can dump straight onto an existing user_data_dir without
            # rewriting headers.
            tf.add(str(full), arcname=rel)

    raw = buf.getvalue()
    cctx = zstd.ZstdCompressor(level=COMPRESS_LEVEL)
    compressed = cctx.compress(raw)

    manifest = {
        "kind": "diff",
        "files": {
            path: {"sha256": sha, "size": size}
            for path, (sha, size) in current.items()
        },
        "added_or_changed": changed,
    }
    return compressed, manifest, changed


def unpack_diff(compressed: bytes, target_dir: Path) -> None:
    """Extract a diff tar+zstd onto ``target_dir`` (overwrite-only).

    ``target_dir`` is created if missing. Uses ``filter='data'`` on
    Python 3.12+ for path-traversal safety; on older runtimes falls back
    to a manual prefix check matching ``profile_snapshot.unpack``.

    NOTE: V1 does not handle deletions — files that existed in the
    parent snapshot but were removed by the user remain on disk after
    restore. See module docstring for the trade-off.
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
            # Python <3.12: replicate the safety check from
            # profile_snapshot.unpack so this fallback isn't a regression.
            safe_members: list[tarfile.TarInfo] = []
            for member in tf.getmembers():
                if member.name.startswith("/"):
                    logger.warning(
                        "unpack_diff: skipping absolute path %s",
                        member.name,
                    )
                    continue
                if ".." in member.name.split("/"):
                    logger.warning(
                        "unpack_diff: skipping traversal %s", member.name
                    )
                    continue
                safe_members.append(member)
            tf.extractall(str(target), members=safe_members)
