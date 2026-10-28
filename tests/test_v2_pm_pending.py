import pytest

from v2_pm_checkpoint_store import (
    PM_EXPORT_HEADERS,
    serialize_checkpoint,
)
from v2_pm_checkpoint import new_export_checkpoint
from v2_pm_pending import unfinished_pm_exports


class FakeSheets:
    def __init__(self, values):
        self.values = values

    def get_all_values(self, tab, refresh=False):
        assert tab == "_PM_Exports_V2"
        return self.values


def checkpoint(state, version="v1"):
    value = new_export_checkpoint(
        document_key="doc",
        version_id=version,
        pdf_sha256="a" * 64,
        output_spreadsheet_id="staging",
        output_tab="Test",
    )
    value["state"] = state
    return value


def sheet(*items):
    return FakeSheets([
        list(PM_EXPORT_HEADERS),
        *(serialize_checkpoint(item) for item in items),
    ])


def test_no_checkpoints():
    assert unfinished_pm_exports(sheet()) == []


def test_completed_checkpoint_is_not_pending():
    assert unfinished_pm_exports(
        sheet(checkpoint("COMPLETED"))
    ) == []


def test_pending_export_detected():
    result = unfinished_pm_exports(
        sheet(checkpoint("EXPORT_PENDING"))
    )
    assert len(result) == 1
    assert result[0]["state"] == "EXPORT_PENDING"


def test_interrupted_export_detected():
    result = unfinished_pm_exports(
        sheet(checkpoint("EXPORTING"))
    )
    assert len(result) == 1


def test_notification_pending_not_silently_ignored():
    result = unfinished_pm_exports(
        sheet(checkpoint("NOTIFICATION_PENDING"))
    )
    assert len(result) == 1


def test_delivery_uncertain_requires_review():
    result = unfinished_pm_exports(
        sheet(checkpoint("DELIVERY_UNCERTAIN"))
    )
    assert len(result) == 1


def test_missing_checkpoint_schema_fails_closed():
    with pytest.raises(ValueError):
        unfinished_pm_exports(FakeSheets([]))
