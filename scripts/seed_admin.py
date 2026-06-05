"""Bootstrap a platform-admin user.

Usage:
    DATABASE_URL=postgresql://... \\
    SEED_EMAIL=admin@example.com \\
    SEED_PASSWORD='change-me-strong' \\
    python -m scripts.seed_admin

Idempotent:
  * If the email doesn't exist, creates a tenant + workspace + user via
    db_auth.signup, then promotes the user to platform admin.
  * If the email already exists, only flips the ``is_platform_admin``
    flag to ``True`` (and does NOT change the password — rotate via
    /api/auth/forgot-password if needed).

Designed to be the ONLY supported way to mint the first admin: a fresh
deployment has zero admins, so the signup-endpoint flow has no admin to
promote you. Once there's at least one admin you can mint additional
admins via ``POST /api/admin/users/{id}/promote``.

Security notes:
  * Reads credentials from env vars so they never land in shell history
    or process listings via argv. Use a secret manager / one-shot env
    file in production.
  * Requires the same ``DATABASE_URL`` the backend uses; runs under
    ``system_context`` so RLS doesn't hide the lookup.
"""
from __future__ import annotations

import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("seed_admin")


def main() -> int:
    email = os.environ.get("SEED_EMAIL")
    password = os.environ.get("SEED_PASSWORD")
    tenant_name = os.environ.get("SEED_TENANT", "Platform")
    if not email or not password:
        logger.error(
            "SEED_EMAIL and SEED_PASSWORD must be set. "
            "Example: SEED_EMAIL=admin@example.com SEED_PASSWORD='xxx' python -m scripts.seed_admin"
        )
        return 2
    if len(password) < 12:
        # Stricter than the signup minimum (8) — this is a privileged
        # account and operators should not bootstrap with a weak secret.
        logger.error("SEED_PASSWORD must be at least 12 characters for a platform-admin account")
        return 2

    # Validate the email the same way /api/auth/login will so we don't
    # bootstrap an account that the user-facing endpoint refuses to
    # authenticate. Catches reserved TLDs (.local, .test, …).
    try:
        from pydantic import TypeAdapter, EmailStr

        TypeAdapter(EmailStr).validate_python(email)
    except Exception as exc:
        logger.error("SEED_EMAIL is not a valid email address: %s", exc)
        return 2

    # Lazy import so a missing DATABASE_URL surfaces from db_auth, not
    # from the argparse layer.
    from backend import db_auth
    from backend.middleware_rls import system_context

    with system_context():
        existing = db_auth.get_user_by_email(email)
        if existing:
            if existing.get("is_platform_admin"):
                logger.info(
                    "User %s already exists and is already a platform admin (id=%s).",
                    email,
                    existing["id"],
                )
                return 0
            ok = db_auth.set_platform_admin(existing["id"], True)
            if not ok:
                logger.error("Failed to flip is_platform_admin for %s", email)
                return 1
            logger.info(
                "Promoted existing user %s (id=%s) to platform admin.",
                email,
                existing["id"],
            )
            return 0

        # Fresh account.
        tenant, user, workspace = db_auth.signup(
            email=email,
            password=password,
            tenant_name=tenant_name,
        )
        db_auth.set_platform_admin(user["id"], True)
        logger.info(
            "Created platform admin: email=%s user_id=%s tenant_id=%s workspace_id=%s",
            user["email"],
            user["id"],
            tenant["id"],
            workspace["id"],
        )
        # Mark email verified so the admin can immediately mint API keys,
        # configure billing, etc., without having to click through a
        # verification link they may never receive on a fresh deployment.
        db_auth.set_email_verified(user["id"])
        logger.info("Email auto-verified for the seeded admin (id=%s).", user["id"])
        return 0


if __name__ == "__main__":
    sys.exit(main())
