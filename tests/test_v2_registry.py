import pytest

from sheets_adapter import (
    DOCUMENT_HEADERS,
    VERSION_HEADERS,
)
from v2_registry import (
    apply_v2_registry,
    build_document_row,
    build_version_row,
    unresolved_author_count,
    version_status,
)


NOW = "2026-10-12T20:00:00+00:00"


def resolved_entry(
    entry_id="A",
    raw_author="Luma Hameed",
):
    return {
        "entry_id": entry_id,
        "raw_author": raw_author,
        "author_status": "RESOLVED",
    }


def unresolved_entry(
    entry_id="B",
    raw_author="user",
):
    return {
        "entry_id": entry_id,
        "raw_author": raw_author,
        "author_status": "NEEDS_REVIEW",
    }


class FakeSheets:
    def __init__(
        self,
        *,
        document_rows=None,
        version_rows=None,
        row_values=None,
    ):
        self.document_rows = (
            document_rows or {}
        )
        self.version_rows = (
            version_rows or {}
        )
        self.row_values = (
            row_values or {}
        )

        self.appends = []
        self.updates = []

    def key_to_row(
        self,
        sheet,
        key_col=0,
    ):
        assert key_col == 0

        if sheet == "_Documents":
            return dict(
                self.document_rows
            )

        if sheet == "_Versions":
            return dict(
                self.version_rows
            )

        raise AssertionError(sheet)

    def get_row_values(
        self,
        sheet,
        row_number,
    ):
        return list(
            self.row_values[
                (
                    sheet,
                    row_number,
                )
            ]
        )

    def append_rows(
        self,
        sheet,
        rows,
    ):
        self.appends.append(
            (
                sheet,
                rows,
            )
        )

    def batch_update_rows(
        self,
        sheet,
        updates,
    ):
        self.updates.append(
            (
                sheet,
                updates,
            )
        )


def make_version(entries):
    return build_version_row(
        document_key=(
            "IGCSE_ARABIC_2P"
        ),
        sha256=("a" * 64),
        drive_file_id="drive-1",
        pdf_name="trial.pdf",
        drive_link="https://example.test",
        modified_time=(
            "2026-10-12T19:00:00Z"
        ),
        size_bytes=12345,
        summary={
            "pages": 323,
            "entries_found": len(
                entries
            ),
            "comments_found": 1,
            "replies_found": 0,
        },
        entries=entries,
        processed_at=NOW,
    )


def make_document(entries):
    return build_document_row(
        document_key=(
            "IGCSE_ARABIC_2P"
        ),
        document_name=(
            "IGCSE Arabic 2P"
        ),
        output_tab=(
            "IGCSE Arabic 2P"
        ),
        master_version="MASTER-1",
        sha256=("a" * 64),
        drive_file_id="drive-1",
        modified_time=(
            "2026-10-12T19:00:00Z"
        ),
        entries=entries,
        processed_at=NOW,
    )


def test_author_review_status():
    entries = [
        resolved_entry(),
        unresolved_entry(),
    ]

    assert (
        unresolved_author_count(
            entries
        )
        == 1
    )

    assert (
        version_status(entries)
        == "NEEDS_AUTHOR_REVIEW"
    )


def test_all_resolved_is_processed():
    entries = [
        resolved_entry(),
    ]

    assert (
        version_status(entries)
        == "PROCESSED"
    )


def test_version_row_matches_schema():
    row = make_version([
        resolved_entry(),
    ])

    assert set(row) == set(
        VERSION_HEADERS
    )

    assert (
        row["Version Status"]
        == "PROCESSED"
    )


def test_document_row_matches_schema():
    row = make_document([
        unresolved_entry(),
    ])

    assert set(row) == set(
        DOCUMENT_HEADERS
    )

    assert (
        row["Status"]
        == "NEEDS_AUTHOR_REVIEW"
    )


def test_first_version_inserts_document_and_version():
    sheets = FakeSheets()

    result = apply_v2_registry(
        sheets,
        document_row=make_document(
            [resolved_entry()]
        ),
        version_row=make_version(
            [resolved_entry()]
        ),
    )

    assert result == {
        "document_inserted": 1,
        "document_updated": 0,
        "version_inserted": 1,
        "version_existing": 0,
    }

    assert [
        sheet
        for sheet, _ in sheets.appends
    ] == [
        "_Documents",
        "_Versions",
    ]

    assert sheets.updates == []


def test_new_version_updates_document_and_appends_version():
    sheets = FakeSheets(
        document_rows={
            "IGCSE_ARABIC_2P": 2,
        }
    )

    result = apply_v2_registry(
        sheets,
        document_row=make_document(
            [resolved_entry()]
        ),
        version_row=make_version(
            [resolved_entry()]
        ),
    )

    assert result[
        "document_updated"
    ] == 1

    assert result[
        "version_inserted"
    ] == 1

    assert len(
        sheets.updates
    ) == 1

    assert (
        sheets.updates[0][0]
        == "_Documents"
    )


def test_existing_identical_version_not_duplicated():
    version = make_version([
        resolved_entry(),
    ])

    version_id = version[
        "Version ID"
    ]

    existing = [
        version["Version ID"],
        version["Document Key"],
        version["Drive File ID"],
        version["PDF Name"],
        version["Drive Link"],
        version["Modified Time"],
        version["Size Bytes"],
        version["PDF SHA256"],
    ]

    sheets = FakeSheets(
        document_rows={
            "IGCSE_ARABIC_2P": 2,
        },
        version_rows={
            version_id: 2,
        },
        row_values={
            (
                "_Versions",
                2,
            ): existing,
        },
    )

    result = apply_v2_registry(
        sheets,
        document_row=make_document(
            [resolved_entry()]
        ),
        version_row=version,
    )

    assert result[
        "version_inserted"
    ] == 0

    assert result[
        "version_existing"
    ] == 1

    assert not any(
        sheet == "_Versions"
        for sheet, _ in sheets.appends
    )


def test_conflicting_existing_version_fails_before_write():
    version = make_version([
        resolved_entry(),
    ])

    sheets = FakeSheets(
        version_rows={
            version["Version ID"]: 2,
        },
        row_values={
            (
                "_Versions",
                2,
            ): [
                version["Version ID"],
                "OTHER_DOCUMENT",
                "",
                "",
                "",
                "",
                "",
                "different-sha",
            ],
        },
    )

    with pytest.raises(
        ValueError,
        match="conflicts",
    ):
        apply_v2_registry(
            sheets,
            document_row=make_document(
                [resolved_entry()]
            ),
            version_row=version,
        )

    assert sheets.appends == []
    assert sheets.updates == []
