import pytest
from v2_release_gate import (
    ensure_v2_runtime_safety, STAGING_PM_ID, PRODUCTION_PM_ID, PM_TAB,
)


def check(monkeypatch, *, destination=STAGING_PM_ID, verified=True,
          mode="OFF", enabled="false", dry_run=False):
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", enabled)
    monkeypatch.setenv("NOTIFICATION_MODE", mode)
    return ensure_v2_runtime_safety(
        v2_enabled=True, dry_run=dry_run,
        output_spreadsheet_id=destination,
        config={"v2_pm_output_spreadsheet_id": destination,
                "v2_pm_output_tab": PM_TAB,
                "v2_require_verified_pm_export": verified},
    )


def test_staging_notifications_off(monkeypatch):
    assert check(monkeypatch)["notification_mode"] == "OFF"


def test_staging_admin_test_with_proof_required(monkeypatch):
    assert check(monkeypatch, mode="TEST", enabled="true")["notification_mode"] == "TEST"


@pytest.mark.parametrize("mode", ["FINAL", "PRODUCTION"])
def test_real_pm_mail_is_blocked_on_staging(monkeypatch, mode):
    with pytest.raises(PermissionError, match="PM_NOTIFICATIONS_NOT_AUTHORIZED"):
        check(monkeypatch, mode=mode, enabled="true")


def test_email_requires_export_proof(monkeypatch):
    with pytest.raises(RuntimeError, match="NOTIFICATIONS_REQUIRE_VERIFIED"):
        check(monkeypatch, verified=False, mode="TEST", enabled="true")


def test_production_write_id_blocked(monkeypatch):
    with pytest.raises(PermissionError, match="PRODUCTION_PM_DESTINATION_NOT_AUTHORIZED"):
        check(monkeypatch, destination=PRODUCTION_PM_ID)


def test_unapproved_destination_blocked(monkeypatch):
    with pytest.raises(PermissionError, match="VERIFIED_EXPORT_DESTINATION_NOT_STAGING"):
        check(monkeypatch, destination="unrecognized-id")


def test_dry_run_never_enables_pm_export_or_email(monkeypatch):
    assert check(monkeypatch, dry_run=True, enabled="false")["mode"] == "V2"


def test_rejects_runtime_destination_mismatch_before_io(monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "false")
    with pytest.raises(PermissionError, match="PM_OUTPUT_DESTINATION_MISMATCH"):
        ensure_v2_runtime_safety(
            v2_enabled=True, dry_run=False,
            config={"v2_pm_output_spreadsheet_id": STAGING_PM_ID,
                    "v2_pm_output_tab": PM_TAB,
                    "v2_pm_staging_apply": True,
                    "v2_require_verified_pm_export": True},
            output_spreadsheet_id=PRODUCTION_PM_ID,
        )
