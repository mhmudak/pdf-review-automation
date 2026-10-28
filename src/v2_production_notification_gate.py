"""Explicit opt-in for production V2 email delivery.

Pure configuration validation: no Google/SMTP calls and no secrets.
Staging keeps TEST-only delivery. Production is disabled unless a
mode-specific, exact authorization marker is present.
"""
from __future__ import annotations

import os

from v2_release_gate import PRODUCTION_PM_ID
ADMIN_TEST_MARKER = "YES_I_AUTHORIZE_PRODUCTION_ADMIN_TEST_EMAIL"
PM_DELIVERY_MARKER = "YES_I_AUTHORIZE_PRODUCTION_PM_EMAILS"
AUTH_ENV = "V2_PRODUCTION_NOTIFICATION_AUTHORIZED"


def ensure_notification_delivery_authorized(
    *,
    destination: str,
    mode: str,
    notifications_on: bool,
    dry_run: bool,
    verified_export_required: bool,
) -> str:
    """Validate the two-phase delivery gate or fail before any I/O.

    Production TEST goes only to ADMIN via the existing delivery policy.
    Production FINAL/PRODUCTION additionally require a stronger PM marker.
    All production modes require the verified-export pipeline and a
    write-enabled execution (not the saved dry-run configuration).
    """
    if not notifications_on:
        return "OFF"

    mode = str(mode).strip().upper()
    destination = str(destination).strip()

    if mode not in {"TEST", "FINAL", "PRODUCTION"}:
        raise PermissionError("NOTIFICATION_MODE_NOT_AUTHORIZED")

    if not verified_export_required:
        raise RuntimeError("NOTIFICATIONS_REQUIRE_VERIFIED_PM_EXPORT")

    if destination != PRODUCTION_PM_ID:
        if mode != "TEST":
            raise PermissionError("PM_NOTIFICATIONS_NOT_AUTHORIZED_ON_STAGING")
        return "STAGING_ADMIN_TEST"

    if dry_run:
        raise PermissionError("PRODUCTION_NOTIFICATIONS_REQUIRE_WRITE_ENABLED_RUN")

    marker = os.getenv(AUTH_ENV, "").strip()
    if mode == "TEST":
        if marker != ADMIN_TEST_MARKER:
            raise PermissionError("PRODUCTION_ADMIN_TEST_EMAIL_NOT_AUTHORIZED")
        return "PRODUCTION_ADMIN_TEST"

    if marker != PM_DELIVERY_MARKER:
        raise PermissionError("PRODUCTION_PM_EMAIL_NOT_AUTHORIZED")

    if mode == "FINAL" and os.getenv("PM_FINAL_TEST_AUTHORIZED", "").strip().lower() not in {"true", "1", "yes"}:
        raise PermissionError("PRODUCTION_FINAL_PM_TEST_NOT_AUTHORIZED")

    return "PRODUCTION_PM_DELIVERY"
