"""Regression tests for verified PM export routing."""

from types import SimpleNamespace

import pytest

import backend_router


class FakeSheets:
    def __init__(self):
        self.appended = []

    def append_rows(self, tab, rows):
        self.appended.append((tab, rows))


def drive_file():
    return SimpleNamespace(
        file_id="file-123",
        name="test.pdf",
        web_view_link="https://example.test/pdf",
        modified_time="2026-10-14T10:00:00Z",
        size=12345,
    )


def call_router(
    monkeypatch,
    *,
    required=True,
    exporter=None,
):
    sheets = FakeSheets()
    executions = []

    def fake_execute(**kwargs):
        executions.append(kwargs)
        return {
            "action": "PROCESSED_V2",
            "entry_changes": {
                "NEW": 0,
                "UNCHANGED": 1,
            },
            "entry_writes": {
                "inserted": 0,
                "updated": 0,
            },
            "author_summary": {
                "unresolved_count": 0,
            },
        }

    monkeypatch.setattr(
        backend_router,
        "execute_v2_pdf",
        fake_execute,
    )

    monkeypatch.setattr(
        backend_router,
        "files_registry_row",
        lambda *args, **kwargs: ["registry-row"],
    )

    def invoke():
        return backend_router.synchronize_processed_pdf(
            v2_enabled=True,
            backend_sheets=sheets,
            output_sheets=None,
            config={
                "v2_require_verified_pm_export": required
            },
            annotations=[],
            summary={"sha256": "a" * 64},
            drive_file=drive_file(),
            run_id="test-run",
            v2_pm_exporter=exporter,
        )

    return sheets, executions, invoke


def test_missing_exporter_blocks_before_backend_write(
    monkeypatch,
):
    sheets, executions, invoke = call_router(
        monkeypatch,
        exporter=None,
    )

    with pytest.raises(
        RuntimeError,
        match="V2_PM_EXPORTER_NOT_CONFIGURED",
    ):
        invoke()

    assert executions == []
    assert sheets.appended == []


def test_failed_export_does_not_mark_processed(
    monkeypatch,
):
    sheets, executions, invoke = call_router(
        monkeypatch,
        exporter=lambda **kwargs: {
            "verified": False
        },
    )

    with pytest.raises(
        RuntimeError,
        match="V2_PM_EXPORT_NOT_VERIFIED",
    ):
        invoke()

    assert len(executions) == 1
    assert sheets.appended == []


def test_exporter_exception_blocks_registry_success(
    monkeypatch,
):
    def exporter(**kwargs):
        raise RuntimeError("MANUAL_EDIT_CONFLICT")

    sheets, _, invoke = call_router(
        monkeypatch,
        exporter=exporter,
    )

    with pytest.raises(
        RuntimeError,
        match="MANUAL_EDIT_CONFLICT",
    ):
        invoke()

    assert sheets.appended == []


def test_verified_export_allows_registry_success(
    monkeypatch,
):
    sheets, _, invoke = call_router(
        monkeypatch,
        exporter=lambda **kwargs: {
            "verified": True
        },
    )

    result = invoke()

    assert result["pm_export"]["verified"] is True
    assert len(sheets.appended) == 1
    assert sheets.appended[0][0] == "_Files"


def test_existing_behavior_preserved_when_flag_disabled(
    monkeypatch,
):
    sheets, _, invoke = call_router(
        monkeypatch,
        required=False,
    )

    result = invoke()

    assert result["pm_export"] is None
    assert len(sheets.appended) == 1
