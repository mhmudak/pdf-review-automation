"""Preflight safety checks for PDF Review Automation V2. No network calls."""
import os

PRODUCTION_PM_ID = "13f31vlPWQPWrt2auGukJA7oWrM-90Kp6yU8OhWT3ERE"
STAGING_PM_ID = "1X4NN9gnvQdXc65cPk9B-p2W-yiBlqZ2rcg8U-ujd2N4"
PM_TAB = "Trial PDF - All Data"


def ensure_v2_runtime_safety(*, v2_enabled, dry_run, config, output_spreadsheet_id):
    """Fail closed on an enabled V2 mode with inconsistent export or mail gates.

    This release does not authorize production PM writes. Notifications must
    remain explicitly opted in, and only verified exports may notify the PM.
    """
    if not v2_enabled:
        return {"mode": "LEGACY"}

    destination = str(config.get("v2_pm_output_spreadsheet_id") or "").strip()
    tab = str(config.get("v2_pm_output_tab") or "").strip()
    require_export = config.get("v2_require_verified_pm_export") is True
    notifications_on = os.environ.get("NOTIFICATIONS_ENABLED", "").strip().lower() in {"true", "1", "yes", "on"}
    notification_mode = os.environ.get("NOTIFICATION_MODE", "OFF").strip().upper()

    production = destination == PRODUCTION_PM_ID
    if production and not (
        config.get("v2_pm_production_apply") is True
        and os.environ.get("V2_PM_PRODUCTION_AUTHORIZED", "")
        == "YES_I_AUTHORIZE_PRODUCTION_PM_WRITES"
    ):
        raise PermissionError("PRODUCTION_PM_DESTINATION_NOT_AUTHORIZED_IN_THIS_RELEASE: EXPLICIT_APPROVAL_REQUIRED")

    if require_export and (destination not in {STAGING_PM_ID, PRODUCTION_PM_ID} or tab != PM_TAB):
        raise PermissionError("VERIFIED_EXPORT_DESTINATION_NOT_STAGING_OR_APPROVED_PRODUCTION")
    if production and not require_export:
        raise PermissionError("PRODUCTION_REQUIRES_VERIFIED_EXPORT")
    if production and notifications_on:
        raise PermissionError("PRODUCTION_PM_NOTIFICATIONS_REQUIRE_SEPARATE_RELEASE")

    if not dry_run and notifications_on:
        if not require_export:
            raise RuntimeError("NOTIFICATIONS_REQUIRE_VERIFIED_PM_EXPORT")
        if notification_mode not in {"TEST", "FINAL", "PRODUCTION"}:
            raise RuntimeError("NOTIFICATION_MODE_INVALID_FOR_ENABLED_DELIVERY")
        if notification_mode in {"FINAL", "PRODUCTION"}:
            raise PermissionError("PM_NOTIFICATIONS_NOT_AUTHORIZED_WITH_STAGING_ONLY_EXPORT")

    return {"mode": "V2", "destination": destination, "require_verified_export": require_export,
            "notification_mode": notification_mode if notifications_on else "OFF"}
