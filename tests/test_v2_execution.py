from v2_execution import execute_v2_pdf


SHA = "a" * 64
NOW = "2026-10-12T20:00:00+00:00"


class FakeSheets:
    def __init__(
        self,
        batch=None,
    ):
        self.batch = batch or {
            "_Documents": [],
            "_Versions": [],
            "_Entries_V2": [],
            "_Author Rules": [],
        }

        self.batch_get_calls = []
        self.appends = []
        self.updates = []

    def batch_get_values(
        self,
        sheets,
        refresh=False,
    ):
        self.batch_get_calls.append(
            (
                list(sheets),
                refresh,
            )
        )

        return self.batch

    def key_to_row(
        self,
        sheet,
        key_col=0,
    ):
        values = self.batch.get(
            sheet,
            [],
        )

        output = {}

        for row_number, row in enumerate(
            values[1:],
            start=2,
        ):
            if (
                len(row) > key_col
                and str(
                    row[key_col]
                ).strip()
            ):
                output[
                    str(
                        row[key_col]
                    ).strip()
                ] = row_number

        return output

    def get_row_values(
        self,
        sheet,
        row_number,
    ):
        values = self.batch.get(
            sheet,
            [],
        )

        index = row_number - 1

        if (
            index < 0
            or index >= len(values)
        ):
            return []

        return list(values[index])

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


def annotation(
    entry_id="A",
    raw_author="emanz",
):
    return {
        "entry_id": entry_id,
        "raw_author": raw_author,
        "content": "Hello",
        "comment": "Hello",
        "entry_type": "COMMENT",
        "relation_type": "ROOT",
        "reply_depth": 0,
        "pdf_page": 1,
        "book_page": 1,
        "annotation_type": "Text",
        "created": "",
        "modified": "",
        "coordinates": "",
        "xref": 10,
    }


def config():
    return {
        "document_key":
            "IGCSE_ARABIC_2P",
        "reviewer_aliases": {
            "emanz":
                "Eman Zahran",
        },
    }


def test_first_v2_pdf_writes_entry_history_document_version():
    sheets = FakeSheets()

    result = execute_v2_pdf(
        sheets=sheets,
        config=config(),
        extracted_rows=[
            annotation()
        ],
        summary={
            "sha256": SHA,
            "pages": 323,
            "entries_found": 1,
        },
        drive_file_id="drive-1",
        pdf_name="trial.pdf",
        drive_link="https://example.test",
        modified_time=(
            "2026-10-12T19:00:00Z"
        ),
        size_bytes=123,
        master_version="MASTER-1",
        processed_at=NOW,
    )

    assert result[
        "action"
    ] == "PROCESSED_V2"

    assert result[
        "entry_changes"
    ]["NEW"] == 1

    assert result[
        "entry_writes"
    ] == {
        "inserted": 1,
        "updated": 0,
        "deactivated": 0,
        "history_appended": 1,
    }

    appended_sheets = [
        sheet
        for sheet, _ in sheets.appends
    ]

    assert "_Entries_V2" in (
        appended_sheets
    )

    assert "_Entry History" in (
        appended_sheets
    )

    assert "_Documents" in (
        appended_sheets
    )

    assert "_Versions" in (
        appended_sheets
    )


def test_known_sha_is_zero_write_duplicate():
    batch = {
        "_Documents": [],
        "_Versions": [
            [
                "Version ID",
                "Document Key",
                "Drive File ID",
                "PDF Name",
                "Drive Link",
                "Modified Time",
                "Size Bytes",
                "PDF SHA256",
            ],
            [
                "existing-version",
                "IGCSE_ARABIC_2P",
                "drive-old",
                "old.pdf",
                "",
                "",
                "",
                SHA,
            ],
        ],
        "_Entries_V2": [],
        "_Author Rules": [],
    }

    sheets = FakeSheets(
        batch=batch
    )

    result = execute_v2_pdf(
        sheets=sheets,
        config=config(),
        extracted_rows=[
            annotation()
        ],
        summary={
            "sha256": SHA,
            "pages": 323,
            "entries_found": 1,
        },
        drive_file_id="drive-new",
        pdf_name="renamed-copy.pdf",
        drive_link="",
        modified_time="",
        size_bytes=123,
        processed_at=NOW,
    )

    assert result[
        "action"
    ] == "DUPLICATE_VERSION"

    assert sheets.appends == []
    assert sheets.updates == []


def test_generic_author_requires_pm_review():
    sheets = FakeSheets()

    result = execute_v2_pdf(
        sheets=sheets,
        config={
            "document_key":
                "IGCSE_ARABIC_2P"
        },
        extracted_rows=[
            annotation(
                raw_author="user"
            )
        ],
        summary={
            "sha256": SHA,
            "pages": 323,
            "entries_found": 1,
        },
        drive_file_id="drive-1",
        pdf_name="trial.pdf",
        drive_link="",
        modified_time="",
        size_bytes=123,
        processed_at=NOW,
    )

    assert (
        result[
            "author_summary"
        ]["unresolved_count"]
        == 1
    )
