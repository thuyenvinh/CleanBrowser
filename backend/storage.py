"""S3-compatible object storage abstraction.

Phase 3 wave 1 (task AAA) — backs the cloud-sync snapshot story from
``docs/ARCHITECTURE`` §2.7. Profile ``user_data_dir`` snapshots
(tar+zstd) are uploaded as immutable objects keyed by
``tenants/{tenant}/profiles/{profile}/v{n}.tar.zst``; the row in
``profile_versions`` (migration 0013) is the index over them.

This module is intentionally provider-agnostic: any S3-compatible
endpoint (AWS S3, MinIO, Wasabi, Backblaze B2 in S3 mode, etc.) works
through :class:`S3Backend` by pointing ``STORAGE_ENDPOINT`` at the right
URL. A :class:`LocalBackend` is used as a development fallback when
``STORAGE_BUCKET`` is not configured, so the API can boot and tests can
exercise the upload/download contract without standing up MinIO.

Configuration (env vars):

* ``STORAGE_BUCKET``         — bucket name. Absent → :class:`LocalBackend`.
* ``STORAGE_ENDPOINT``       — optional, e.g. ``https://minio.local:9000``.
                                Omit for AWS S3.
* ``STORAGE_REGION``         — defaults to ``us-east-1``.
* ``STORAGE_ACCESS_KEY``     — IAM access key id.
* ``STORAGE_SECRET_KEY``     — IAM secret access key.

The module is import-safe even when ``boto3`` is not installed — the
import is deferred until :class:`S3Backend` is actually instantiated, so
dev environments running on the local fallback never need the dependency
at process start.

Not yet wired into :mod:`backend.browser_manager`; that adoption lands
in agent BBB's task.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
from pathlib import Path
from typing import BinaryIO

logger = logging.getLogger("cloakbrowser.storage")


def is_configured() -> bool:
    """True iff S3-style storage is configured via env vars.

    The minimum signal is ``STORAGE_BUCKET``; access keys may legitimately
    come from instance metadata / IRSA on AWS, so we don't insist on them
    here. Callers that need to know whether they will hit a real bucket
    or the local dev fallback should use this helper rather than
    re-implementing the env check.
    """

    return bool(os.environ.get("STORAGE_BUCKET"))


# ---------------------------------------------------------------------------
# Backend interface
# ---------------------------------------------------------------------------


class StorageBackend:
    """Abstract S3-compatible backend.

    Subclasses must implement all five methods. ``upload`` accepts either
    raw ``bytes`` or a binary file-like object so callers can stream large
    snapshots without materialising them in memory; the ``size_bytes`` /
    ``sha256`` fields in the returned dict are best-effort and may be
    ``None`` for streamed uploads where the backend can't cheaply compute
    them without a second pass.
    """

    def upload(self, key: str, data: bytes | BinaryIO) -> dict:
        raise NotImplementedError

    def download(self, key: str) -> bytes:
        raise NotImplementedError

    def delete(self, key: str) -> bool:
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        raise NotImplementedError

    def presigned_url(self, key: str, expires_in: int = 3600) -> str:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# S3-compatible backend (AWS S3, MinIO, Wasabi, ...)
# ---------------------------------------------------------------------------


class S3Backend(StorageBackend):
    """boto3-backed implementation of :class:`StorageBackend`.

    ``boto3`` is imported lazily inside ``__init__`` so that simply
    importing :mod:`backend.storage` never pulls in the AWS SDK. This
    matters because the local dev fallback (:class:`LocalBackend`) is
    used when ``STORAGE_BUCKET`` is unset, and we don't want to force
    devs to install boto3 just to run unit tests.
    """

    def __init__(self) -> None:
        import boto3  # local import — see class docstring

        self.bucket = os.environ["STORAGE_BUCKET"]
        kwargs: dict = {
            "region_name": os.environ.get("STORAGE_REGION", "us-east-1"),
            "aws_access_key_id": os.environ.get("STORAGE_ACCESS_KEY"),
            "aws_secret_access_key": os.environ.get("STORAGE_SECRET_KEY"),
        }
        endpoint = os.environ.get("STORAGE_ENDPOINT")
        if endpoint:
            # MinIO / Wasabi / B2 — point boto3 at the custom endpoint.
            kwargs["endpoint_url"] = endpoint
        self.client = boto3.client("s3", **kwargs)

    def upload(self, key: str, data: bytes | BinaryIO) -> dict:
        if isinstance(data, (bytes, bytearray)):
            payload = bytes(data)
            size = len(payload)
            sha = hashlib.sha256(payload).hexdigest()
            body: BinaryIO = io.BytesIO(payload)
        else:
            # Stream as-is; size/sha left for the caller to compute if
            # they need the integrity hash (e.g. by tee'ing through a
            # hashing wrapper).
            body = data
            size = None
            sha = None
        self.client.put_object(Bucket=self.bucket, Key=key, Body=body)
        return {"key": key, "size_bytes": size, "sha256": sha}

    def download(self, key: str) -> bytes:
        resp = self.client.get_object(Bucket=self.bucket, Key=key)
        return resp["Body"].read()

    def delete(self, key: str) -> bool:
        self.client.delete_object(Bucket=self.bucket, Key=key)
        return True

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            # boto3 raises ClientError(404) for missing keys; we
            # deliberately swallow all exceptions here so callers get a
            # clean bool. Real failures (auth, network) will surface on
            # the next get/put.
            return False

    def presigned_url(self, key: str, expires_in: int = 3600) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )


# ---------------------------------------------------------------------------
# Local filesystem fallback (dev / tests)
# ---------------------------------------------------------------------------


class LocalBackend(StorageBackend):
    """Filesystem-backed fallback used when ``STORAGE_BUCKET`` is unset.

    Stores every object under ``root`` (default ``/data/snapshots``) with
    ``/`` in the key replaced by ``__`` so we keep a flat directory tree
    and avoid surprises with intermediate symlinks. ``presigned_url``
    returns a ``file://`` URL — *not* a real signed URL, just a uniform
    return type so calling code can treat both backends identically in
    dev mode.
    """

    def __init__(self, root: str = "/data/snapshots") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Flatten the key — '/' in S3 keys is purely virtual; on a real
        # filesystem it would create directories we'd then have to clean
        # up. Using '__' keeps a 1:1 mapping that's easy to reverse.
        return self.root / key.replace("/", "__")

    def upload(self, key: str, data: bytes | BinaryIO) -> dict:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, (bytes, bytearray)):
            payload = bytes(data)
            p.write_bytes(payload)
            size = len(payload)
            sha = hashlib.sha256(payload).hexdigest()
        else:
            raw = data.read()
            p.write_bytes(raw)
            size = len(raw)
            sha = hashlib.sha256(raw).hexdigest()
        return {"key": key, "size_bytes": size, "sha256": sha}

    def download(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> bool:
        p = self._path(key)
        if p.exists():
            p.unlink()
            return True
        return False

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def presigned_url(self, key: str, expires_in: int = 3600) -> str:
        # Not actually presigned — the local backend has no auth layer to
        # sign against. Returned as a ``file://`` URL purely so the API
        # surface is uniform between dev and prod.
        return f"file://{self._path(key)}"


# ---------------------------------------------------------------------------
# Module-level singleton + convenience helpers
# ---------------------------------------------------------------------------


_backend: StorageBackend | None = None


def get_backend() -> StorageBackend:
    """Return the process-wide :class:`StorageBackend` singleton.

    First call decides which backend to use based on
    :func:`is_configured`. The choice is cached for the life of the
    process — switching backends mid-run would be a footgun, and tests
    that need to swap should call :func:`reset_backend` explicitly.
    """

    global _backend
    if _backend is None:
        if is_configured():
            _backend = S3Backend()
            logger.info(
                "storage: using S3 backend, bucket=%s",
                os.environ["STORAGE_BUCKET"],
            )
        else:
            _backend = LocalBackend()
            logger.warning(
                "storage: STORAGE_BUCKET not set, using LocalBackend at %s",
                _backend.root,
            )
    return _backend


def reset_backend() -> None:
    """Drop the cached backend (test hook)."""

    global _backend
    _backend = None


def upload(key: str, data: bytes | BinaryIO) -> dict:
    return get_backend().upload(key, data)


def download(key: str) -> bytes:
    return get_backend().download(key)


def delete(key: str) -> bool:
    return get_backend().delete(key)


def exists(key: str) -> bool:
    return get_backend().exists(key)


def presigned_url(key: str, expires_in: int = 3600) -> str:
    return get_backend().presigned_url(key, expires_in)


def make_profile_snapshot_key(
    tenant_id: str, profile_id: str, version: int
) -> str:
    """Standardised S3 key for a profile snapshot.

    Matches the layout described in ``docs/ARCHITECTURE`` §2.7. Kept in
    one place so the browser_manager (writer) and any future restore
    flow (reader) cannot drift from the ``profile_versions.storage_key``
    column shape.
    """

    return f"tenants/{tenant_id}/profiles/{profile_id}/v{version}.tar.zst"
