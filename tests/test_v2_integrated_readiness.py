from types import SimpleNamespace
import pytest
import v2_pm_export_coordinator as coordinator
from registry import build_registry
from v2_pipeline_notifications import verified_identical_upload_ack
from v2_pm_checkpoint import new_export_checkpoint
from v2_pm_checkpoint_store import serialize_checkpoint

SHA = "a" * 64
DOC = "IGCSE_ARABIC_2P"
VERSION = DOC + "@" + SHA


def checkpoint(state="COMPLETED", version=VERSION):
    c = new_export_checkpoint(
        document_key=DOC, version_id=version, pdf_sha256=SHA,
        output_spreadsheet_id=coordinator.STAGING_ID,
        output_tab=coordinator.PM_TAB,
    )
    c["state"] = state
    c["verified_projection_digest"] = "verified-hash" if state == "COMPLETED" else ""
    return c


class FakeAdapter:
    checkpoint_rows = []
    def __init__(self, spreadsheet_id):
        assert spreadsheet_id == coordinator.STAGING_ID
    def get_all_values(self, tab, refresh=False):
        assert tab == "_PM_Exports_V2"
        from v2_pm_checkpoint_store import PM_EXPORT_HEADERS
        return [PM_EXPORT_HEADERS, *self.checkpoint_rows]


def invoke(monkeypatch, state="COMPLETED", version=VERSION):
    monkeypatch.setattr(coordinator, "SheetsAdapter", FakeAdapter)
    FakeAdapter.checkpoint_rows = [serialize_checkpoint(checkpoint(state, version))]
    return coordinator.export_verified_pm(
        backend_sheets=SimpleNamespace(get_all_values=lambda *a, **k:
            (_ for _ in ()).throw(AssertionError("heavy backend read"))),
        output_sheets=None,
        v2_result={"action": "DUPLICATE_VERSION", "document_key": DOC,
                   "version_id": VERSION, "sha256": SHA},
        drive_file=None,
        config={"v2_pm_staging_apply": True,
                "v2_pm_output_spreadsheet_id": coordinator.STAGING_ID,
                "v2_pm_output_tab": coordinator.PM_TAB},
    )


def test_completed_duplicate_uses_checkpoint_without_projection(monkeypatch):
    result = invoke(monkeypatch)
    assert result["verified"] is True
    assert result["action"] == "ALREADY_EXPORTED"
    assert result["reused_completed_checkpoint"] is True


@pytest.mark.parametrize("state", ["EXPORT_PENDING", "EXPORTING", "EXPORT_VERIFIED"])
def test_incomplete_checkpoint_does_not_fast_skip(monkeypatch, state):
    with pytest.raises(AssertionError, match="heavy backend read"):
        invoke(monkeypatch, state)


def test_prior_completed_version_does_not_fast_skip(monkeypatch):
    with pytest.raises(AssertionError, match="heavy backend read"):
        invoke(monkeypatch, "COMPLETED", "other-version")


def test_production_destination_still_locked(monkeypatch):
    with pytest.raises(PermissionError, match="STAGING_DESTINATION_ONLY"):
        coordinator.export_verified_pm(
            backend_sheets=object(), output_sheets=None,
            v2_result={"action": "DUPLICATE_VERSION", "document_key": DOC,
                       "version_id": VERSION, "sha256": SHA},
            drive_file=None,
            config={"v2_pm_staging_apply": True,
                    "v2_pm_output_spreadsheet_id": "production-id",
                    "v2_pm_output_tab": coordinator.PM_TAB},
        )


def test_failed_sha_registry_record_does_not_prove_duplicate():
    from sheets_adapter import FILES_HEADERS
    row = ["old-id", "file.pdf", "", "today", "123", SHA, "", "ERROR"]
    by_id, by_sha = build_registry([FILES_HEADERS, row])
    assert "old-id" in by_id
    assert SHA not in by_sha


def test_duplicate_ack_requires_completed_matching_file():
    result = verified_identical_upload_ack(
        file_id="new", sha256=SHA, previous_file=None,
        matching_file=SimpleNamespace(file_id="old", sha256=SHA, status="ERROR"),
        route_result={"pm_export_result": {"verified": True, "export_id": "e"}},
    )
    assert result is None
