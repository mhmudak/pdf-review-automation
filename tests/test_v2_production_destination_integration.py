"""Fail-closed production routing and baseline tests. No live APIs."""
import pytest

from v2_pm_export_coordinator import (
    STAGING_ID, PRODUCTION_ID, PM_TAB,
    export_destination, require_destination_bootstrap,
)
from v2_release_gate import ensure_v2_runtime_safety


def config(destination, *, production=False, staging=False):
    return {
        "v2_pm_output_spreadsheet_id": destination,
        "v2_pm_output_tab": PM_TAB,
        "v2_pm_staging_apply": staging,
        "v2_pm_production_apply": production,
        "v2_require_verified_pm_export": True,
    }


def test_staging_remains_available_only_when_explicit():
    with pytest.raises(PermissionError, match="STAGING_APPLY"):
        export_destination(config(STAGING_ID))
    assert export_destination(config(STAGING_ID, staging=True)) == STAGING_ID


def test_production_requires_both_separate_authorizations(monkeypatch):
    monkeypatch.delenv("V2_PM_PRODUCTION_AUTHORIZED", raising=False)
    with pytest.raises(PermissionError, match="EXPLICIT_APPROVAL"):
        export_destination(config(PRODUCTION_ID, production=True))
    monkeypatch.setenv("V2_PM_PRODUCTION_AUTHORIZED", "YES_I_AUTHORIZE_PRODUCTION_PM_WRITES")
    with pytest.raises(PermissionError, match="EXPLICIT_APPROVAL"):
        export_destination(config(PRODUCTION_ID))
    assert export_destination(config(PRODUCTION_ID, production=True)) == PRODUCTION_ID


def test_production_admin_notifications_require_separate_authorization(monkeypatch):
    monkeypatch.setenv("V2_PM_PRODUCTION_AUTHORIZED", "YES_I_AUTHORIZE_PRODUCTION_PM_WRITES")
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setenv("NOTIFICATION_MODE", "TEST")
    monkeypatch.delenv("V2_PRODUCTION_NOTIFICATION_AUTHORIZED", raising=False)

    with pytest.raises(PermissionError, match="PRODUCTION_ADMIN_TEST_EMAIL_NOT_AUTHORIZED"):
        export_destination(config(PRODUCTION_ID, production=True))

    monkeypatch.setenv(
        "V2_PRODUCTION_NOTIFICATION_AUTHORIZED",
        "YES_I_AUTHORIZE_PRODUCTION_ADMIN_TEST_EMAIL",
    )
    assert export_destination(config(PRODUCTION_ID, production=True)) == PRODUCTION_ID


def test_wrong_destination_or_tab_cannot_be_authorized(monkeypatch):
    monkeypatch.setenv("V2_PM_PRODUCTION_AUTHORIZED", "YES_I_AUTHORIZE_PRODUCTION_PM_WRITES")
    with pytest.raises(PermissionError, match="NOT_ALLOWLISTED"):
        export_destination(config("other", production=True))
    c = config(PRODUCTION_ID, production=True)
    c["v2_pm_output_tab"] = "Osama"
    with pytest.raises(PermissionError, match="TAB_NOT_AUTHORIZED"):
        export_destination(c)


def test_production_requires_existing_verified_baseline(monkeypatch):
    import v2_pm_export_coordinator as module
    called = []
    monkeypatch.setattr(module, "read_source_snapshot", lambda adapter, tab: called.append(("source", tab)))
    monkeypatch.setattr(module, "read_checkpoint_table", lambda adapter: called.append(("checkpoint", None)))
    require_destination_bootstrap(object(), PRODUCTION_ID)
    assert called == [("source", "_PM_Source_Baseline_V2"), ("checkpoint", None)]
    called.clear()
    require_destination_bootstrap(object(), STAGING_ID)
    assert called == []


def test_baseline_missing_blocks_before_writes(monkeypatch):
    import v2_pm_export_coordinator as module
    monkeypatch.setattr(module, "read_source_snapshot", lambda adapter, tab: (_ for _ in ()).throw(RuntimeError("BASELINE_MISSING")))
    with pytest.raises(RuntimeError, match="BASELINE_MISSING"):
        require_destination_bootstrap(object(), PRODUCTION_ID)


def test_runtime_release_gate_enforces_same_production_consent(monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "false")
    monkeypatch.setenv("V2_PM_PRODUCTION_AUTHORIZED", "YES_I_AUTHORIZE_PRODUCTION_PM_WRITES")
    c = config(PRODUCTION_ID, production=True)
    result = ensure_v2_runtime_safety(v2_enabled=True, dry_run=False, config=c, output_spreadsheet_id=PRODUCTION_ID)
    assert result["destination"] == PRODUCTION_ID
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setenv("NOTIFICATION_MODE", "TEST")
    monkeypatch.delenv("V2_PRODUCTION_NOTIFICATION_AUTHORIZED", raising=False)

    with pytest.raises(PermissionError, match="PRODUCTION_ADMIN_TEST_EMAIL_NOT_AUTHORIZED"):
        ensure_v2_runtime_safety(v2_enabled=True, dry_run=False, config=c, output_spreadsheet_id=PRODUCTION_ID)

    monkeypatch.setenv(
        "V2_PRODUCTION_NOTIFICATION_AUTHORIZED",
        "YES_I_AUTHORIZE_PRODUCTION_ADMIN_TEST_EMAIL",
    )
    result = ensure_v2_runtime_safety(v2_enabled=True, dry_run=False, config=c, output_spreadsheet_id=PRODUCTION_ID)
    assert result["notification_mode"] == "TEST"


def test_runtime_production_denies_unverified_export(monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "false")
    monkeypatch.setenv("V2_PM_PRODUCTION_AUTHORIZED", "YES_I_AUTHORIZE_PRODUCTION_PM_WRITES")
    c = config(PRODUCTION_ID, production=True)
    c["v2_require_verified_pm_export"] = False
    with pytest.raises(PermissionError, match="PRODUCTION_REQUIRES_VERIFIED_EXPORT"):
        ensure_v2_runtime_safety(v2_enabled=True, dry_run=False, config=c, output_spreadsheet_id=PRODUCTION_ID)
