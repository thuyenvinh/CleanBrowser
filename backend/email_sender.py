"""Email sender. Uses stdlib smtplib synchronously.

Configure via env: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM,
SMTP_STARTTLS.

When ``SMTP_HOST`` is not set the module falls back to a *dev mode* that just
logs the rendered email body to stdout — this keeps signup working in tests
and on a freshly-cloned dev box without forcing operators to spin up an SMTP
server. The bool return contract stays the same in both modes so callers can
treat "queued" and "logged-in-dev" identically.

Synchronous on purpose: SMTP submission is rare (signup + resend), happens
inside an explicit ``try/except`` on the request path, and adding aiosmtplib
would pull in a dependency for ~10 lines of business logic. The auth router
fires-and-forgets via a plain ``try`` so a slow SMTP server can't make signup
hang past its own ``timeout=10``.
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    """Whether real SMTP submission is wired up (vs dev-mode logging)."""
    return bool(os.environ.get("SMTP_HOST"))


def send(
    to: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
) -> bool:
    """Send email. Returns ``True`` if sent (or logged in dev mode), ``False`` on hard failure.

    Dev mode (no ``SMTP_HOST``) logs the rendered body at INFO so a developer
    clicking a verification link from the server log can complete the flow
    without a real mailer in front of them.
    """
    if not is_configured():
        logger.info(
            "[email-dev-mode] To=%s Subject=%s\n%s", to, subject, body_text
        )
        return True

    msg = EmailMessage()
    msg["From"] = os.environ.get("SMTP_FROM", "no-reply@cleanbrowser.local")
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")

    try:
        host = os.environ["SMTP_HOST"]
        port = int(os.environ.get("SMTP_PORT", "587"))
        with smtplib.SMTP(host, port, timeout=10) as s:
            if os.environ.get("SMTP_STARTTLS", "true").lower() == "true":
                s.starttls()
            user = os.environ.get("SMTP_USER")
            pwd = os.environ.get("SMTP_PASSWORD")
            if user and pwd:
                s.login(user, pwd)
            s.send_message(msg)
        return True
    except Exception:
        # Never let SMTP transport bubble up — the caller treats False as
        # "tell the user we couldn't send" and the auth router itself wraps
        # signup-time sends in its own try/except so a dead mailer doesn't
        # block account creation.
        logger.exception("SMTP send failed to %s", to)
        return False


def send_verification_email(to: str, verify_url: str) -> bool:
    """Render + send the email-verification message for ``to``."""
    subject = "Verify your CleanBrowser email"
    text = (
        "Click the link to verify your email:\n\n"
        f"{verify_url}\n\n"
        "Link expires in 24 hours."
    )
    html = (
        f'<p>Click <a href="{verify_url}">here to verify</a>. '
        "Expires in 24 hours.</p>"
    )
    return send(to, subject, text, html)
