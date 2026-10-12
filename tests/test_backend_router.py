from types import SimpleNamespace

import backend_router


def drive_file():
    return SimpleNamespace(
        file_id="drive-1",
        name="trial.pdf",
        web_view_link="https://example.test",
        modified_time=(
            "2026-10-12T19:00:00Z"
        ),
        size=123,
    )



class FakeSheets:
    def __init__(self):
        self.appends = []

    def append_rows(
        self,
        sheet,
        rows,
    ):
        self.appends.append(
            (sheet, rows)
        )


def test_v2_routes_only_to_v2(
    monkeypatch,
):
    backend = FakeSheets()

    called = {
        "v2": 0,
        "legacy": 0,
    }

    def fake_v2(**kwargs):
        called["v2"] += 1

        assert (
            kwargs["sheets"]
            is backend
        )

        return {
            "action": "PROCESSED_V2",
            "author_summary": {
                "resolved_count": 1,
                "unresolved_count": 0,
            },
            "entry_changes": {
                "NEW": 1,
                "UPDATED": 0,
                "AUTHOR_UPDATED": 0,
                "UNCHANGED": 0,
                "REMOVED": 0,
            },
            "entry_writes": {
                "inserted": 1,
                "updated": 0,
                "deactivated": 0,
                "history_appended": 1,
            },
        }

    def fake_legacy(*args, **kwargs):
        called["legacy"] += 1
        raise AssertionError(
            "legacy sync must not run"
        )

    monkeypatch.setattr(
        backend_router,
        "execute_v2_pdf",
        fake_v2,
    )

    monkeypatch.setattr(
        backend_router,
        "sync_annotations",
        fake_legacy,
    )

    result = (
        backend_router
        .synchronize_processed_pdf(
            v2_enabled=True,
            backend_sheets=backend,
            output_sheets=None,
            config={
                "document_key":
                    "IGCSE_ARABIC_2P"
            },
            annotations=[
                {
                    "entry_id": "A",
                }
            ],
            summary={
                "sha256": "a" * 64,
            },
            drive_file=drive_file(),
            run_id="run-1",
            master_version="MASTER-1",
        )
    )

    assert called == {
        "v2": 1,
        "legacy": 0,
    }

    assert result["mode"] == "V2"
    assert result["duplicate"] is False

    assert [
        sheet
        for sheet, _ in backend.appends
    ] == ["_Files"]


def test_legacy_routes_only_to_legacy(
    monkeypatch,
):
    backend = FakeSheets()
    output = object()

    called = {
        "v2": 0,
        "legacy": 0,
    }

    def fake_v2(**kwargs):
        called["v2"] += 1
        raise AssertionError(
            "v2 must not run"
        )

    def fake_legacy(
        backend_sheets,
        output_sheets,
        annotations,
        file_id,
        drive_link,
        run_id,
        reviewer_tab_map,
    ):
        called["legacy"] += 1

        assert backend_sheets is backend
        assert output_sheets is output

        return {
            "inserted": 1,
            "updated": 0,
            "unchanged": 0,
        }

    monkeypatch.setattr(
        backend_router,
        "execute_v2_pdf",
        fake_v2,
    )

    monkeypatch.setattr(
        backend_router,
        "sync_annotations",
        fake_legacy,
    )

    result = (
        backend_router
        .synchronize_processed_pdf(
            v2_enabled=False,
            backend_sheets=backend,
            output_sheets=output,
            config={
                "reviewer_output_tabs":
                    {}
            },
            annotations=[],
            summary={
                "sha256": "a" * 64,
            },
            drive_file=drive_file(),
            run_id="run-1",
        )
    )

    assert called == {
        "v2": 0,
        "legacy": 1,
    }

    assert (
        result["mode"]
        == "LEGACY"
    )


def test_v2_does_not_require_output_sheet(
    monkeypatch,
):
    backend = FakeSheets()

    monkeypatch.setattr(
        backend_router,
        "execute_v2_pdf",
        lambda **kwargs: {
            "action": "PROCESSED_V2",
            "author_summary": {
                "unresolved_count": 0,
            },
            "entry_changes": {},
            "entry_writes": {},
        },
    )

    result = (
        backend_router
        .synchronize_processed_pdf(
            v2_enabled=True,
            backend_sheets=backend,
            output_sheets=None,
            config={
                "document_key":
                    "IGCSE_ARABIC_2P"
            },
            annotations=[],
            summary={
                "sha256": "a" * 64,
            },
            drive_file=drive_file(),
            run_id="run-1",
        )
    )

    assert result["mode"] == "V2"


def test_legacy_requires_output_sheet():
    backend = FakeSheets()

    try:
        backend_router.synchronize_processed_pdf(
            v2_enabled=False,
            backend_sheets=backend,
            output_sheets=None,
            config={},
            annotations=[],
            summary={},
            drive_file=drive_file(),
            run_id="run-1",
        )
    except ValueError as exc:
        assert (
            "requires output_sheets"
            in str(exc)
        )
    else:
        raise AssertionError(
            "Expected ValueError"
        )


def test_v2_duplicate_is_registered_as_duplicate(
    monkeypatch,
):
    backend = FakeSheets()

    monkeypatch.setattr(
        backend_router,
        "execute_v2_pdf",
        lambda **kwargs: {
            "action":
                "DUPLICATE_VERSION",
            "entry_changes": {
                "NEW": 0,
                "UPDATED": 0,
                "AUTHOR_UPDATED": 0,
                "UNCHANGED": 0,
                "REMOVED": 0,
            },
            "entry_writes": {
                "inserted": 0,
                "updated": 0,
                "deactivated": 0,
                "history_appended": 0,
            },
        },
    )

    result = (
        backend_router
        .synchronize_processed_pdf(
            v2_enabled=True,
            backend_sheets=backend,
            output_sheets=None,
            config={
                "document_key":
                    "IGCSE_ARABIC_2P"
            },
            annotations=[],
            summary={
                "sha256": "a" * 64,
            },
            drive_file=drive_file(),
            run_id="run-1",
        )
    )

    assert result["duplicate"] is True


def test_processed_registry_entry_status():
    entry = (
        backend_router
        .registry_entry_for_processed_pdf(
            drive_file(),
            {
                "sha256":
                    "a" * 64,
            },
        )
    )

    assert entry.status == "PROCESSED"
    assert entry.sha256 == "a" * 64


def test_duplicate_registry_entry_status():
    entry = (
        backend_router
        .registry_entry_for_processed_pdf(
            drive_file(),
            {
                "sha256":
                    "a" * 64,
            },
            duplicate=True,
        )
    )

    assert entry.status == "DUPLICATE"
