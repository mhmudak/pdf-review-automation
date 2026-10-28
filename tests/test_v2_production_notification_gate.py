import pytest

from job_runner import run_once
from v2_production_notification_gate import (
    ADMIN_TEST_MARKER,
    PM_DELIVERY_MARKER,
    PRODUCTION_PM_ID,
    ensure_notification_delivery_authorized as authorize,
)
from v2_release_gate import ensure_v2_runtime_safety


def validate(monkeypatch, *, mode, marker="", dry_run=False, verified=True, destination=PRODUCTION_PM_ID):
    monkeypatch.setenv("V2_PRODUCTION_NOTIFICATION_AUTHORIZED", marker)
    monkeypatch.setenv("PM_FINAL_TEST_AUTHORIZED", "true")
    return authorize(
        destination=destination,
        mode=mode,
        notifications_on=True,
        dry_run=dry_run,
        verified_export_required=verified,
    )


@pytest.mark.parametrize("mode", ["TEST", "FINAL", "PRODUCTION", "OFF", "INVALID"])
def test_production_default_deny(monkeypatch, mode):
    with pytest.raises(PermissionError):
        validate(monkeypatch, mode=mode)


def test_admin_test_requires_exact_marker(monkeypatch):
    assert validate(monkeypatch, mode="TEST", marker=ADMIN_TEST_MARKER) == "PRODUCTION_ADMIN_TEST"


def test_admin_marker_cannot_authorize_pm(monkeypatch):
    with pytest.raises(PermissionError, match="PRODUCTION_PM_EMAIL_NOT_AUTHORIZED"):
        validate(monkeypatch, mode="PRODUCTION", marker=ADMIN_TEST_MARKER)


def test_pm_marker_cannot_authorize_admin_test(monkeypatch):
    with pytest.raises(PermissionError, match="PRODUCTION_ADMIN_TEST_EMAIL_NOT_AUTHORIZED"):
        validate(monkeypatch, mode="TEST", marker=PM_DELIVERY_MARKER)


def test_pm_authorized_but_not_on_dry_run(monkeypatch):
    with pytest.raises(PermissionError, match="WRITE_ENABLED"):
        validate(monkeypatch, mode="PRODUCTION", marker=PM_DELIVERY_MARKER, dry_run=True)


def test_pm_authorized_but_not_without_verified_export(monkeypatch):
    with pytest.raises(RuntimeError, match="VERIFIED"):
        validate(monkeypatch, mode="PRODUCTION", marker=PM_DELIVERY_MARKER, verified=False)


def test_pm_production_authorized(monkeypatch):
    assert validate(monkeypatch, mode="PRODUCTION", marker=PM_DELIVERY_MARKER) == "PRODUCTION_PM_DELIVERY"


def test_final_test_requires_own_approval(monkeypatch):
    monkeypatch.delenv("PM_FINAL_TEST_AUTHORIZED", raising=False)
    monkeypatch.setenv("V2_PRODUCTION_NOTIFICATION_AUTHORIZED", PM_DELIVERY_MARKER)
    with pytest.raises(PermissionError, match="FINAL_PM_TEST_NOT_AUTHORIZED"):
        authorize(destination=PRODUCTION_PM_ID, mode="FINAL", notifications_on=True, dry_run=False, verified_export_required=True)


def test_staging_never_uses_production_mode(monkeypatch):
    with pytest.raises(PermissionError, match="STAGING"):
        validate(monkeypatch, mode="PRODUCTION", marker=PM_DELIVERY_MARKER, destination="staging-id")


def test_disabled_needs_no_marker(monkeypatch):
    assert authorize(destination=PRODUCTION_PM_ID, mode="OFF", notifications_on=False, dry_run=True, verified_export_required=False) == "OFF"


def test_runtime_gate_production_admin_test(monkeypatch):
    monkeypatch.setenv("V2_PM_PRODUCTION_AUTHORIZED", "YES_I_AUTHORIZE_PRODUCTION_PM_WRITES")
    monkeypatch.setenv("V2_PRODUCTION_NOTIFICATION_AUTHORIZED", ADMIN_TEST_MARKER)
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setenv("NOTIFICATION_MODE", "TEST")
    value=ensure_v2_runtime_safety(
        v2_enabled=True, dry_run=False,
        config={"v2_pm_output_spreadsheet_id":PRODUCTION_PM_ID,
                "v2_pm_output_tab":"Trial PDF - All Data",
                "v2_pm_production_apply":True,
                "v2_require_verified_pm_export":True},
        output_spreadsheet_id=PRODUCTION_PM_ID,
    )
    assert value["notification_mode"]=="TEST"


def test_runtime_gate_production_pm(monkeypatch):
    monkeypatch.setenv("V2_PM_PRODUCTION_AUTHORIZED", "YES_I_AUTHORIZE_PRODUCTION_PM_WRITES")
    monkeypatch.setenv("V2_PRODUCTION_NOTIFICATION_AUTHORIZED", PM_DELIVERY_MARKER)
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setenv("NOTIFICATION_MODE", "PRODUCTION")
    value=ensure_v2_runtime_safety(
        v2_enabled=True, dry_run=False,
        config={"v2_pm_output_spreadsheet_id":PRODUCTION_PM_ID,
                "v2_pm_output_tab":"Trial PDF - All Data",
                "v2_pm_production_apply":True,
                "v2_require_verified_pm_export":True},
        output_spreadsheet_id=PRODUCTION_PM_ID,
    )
    assert value["notification_mode"]=="PRODUCTION"


def test_job_blocks_pm_token_without_prod_destination(monkeypatch):
    monkeypatch.setenv("WORKFLOW2_V2_ENABLED", "true")
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setenv("NOTIFICATION_MODE", "PRODUCTION")
    monkeypatch.setenv("WORKFLOW2_OUTPUT_SPREADSHEET_ID", "staging-id")
    monkeypatch.setenv("V2_PRODUCTION_NOTIFICATION_AUTHORIZED", PM_DELIVERY_MARKER)
    with pytest.raises(PermissionError):
        run_once(lambda: {"files_seen":0,"results":[]})


def test_job_authorized_admin_mode_still_no_io_in_mock(monkeypatch):
    monkeypatch.setenv("WORKFLOW2_V2_ENABLED", "true")
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setenv("NOTIFICATION_MODE", "TEST")
    monkeypatch.setenv("WORKFLOW2_DRY_RUN", "false")
    monkeypatch.setenv("WORKFLOW2_OUTPUT_SPREADSHEET_ID", PRODUCTION_PM_ID)
    monkeypatch.setenv("V2_PRODUCTION_NOTIFICATION_AUTHORIZED", ADMIN_TEST_MARKER)
    assert run_once(lambda: {"files_seen":0,"results":[]})["files_seen"] == 0
