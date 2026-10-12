from author_review import (
    approved_rules_from_review_values,
    build_author_review_rows,
    upsert_author_review_rows,
)
from sheets_adapter import AUTHOR_REVIEW_HEADERS


def entry(
    entry_id,
    raw_author,
    *,
    status="NEEDS_REVIEW",
    page=1,
    content="Sample",
):
    return {
        "document_key": "BOOK",
        "version_id": "BOOK@V1",
        "entry_id": entry_id,
        "raw_author": raw_author,
        "author_status": status,
        "book_page": page,
        "content": content,
    }


class FakeSheets:
    def __init__(
        self,
        rows=None,
    ):
        self.rows = rows or []
        self.appends = []
        self.updates = []

    def key_to_row(
        self,
        sheet,
        key_col=0,
    ):
        assert sheet == "_Author Review"

        output = {}

        for number, row in enumerate(
            self.rows[1:],
            start=2,
        ):
            if len(row) > key_col:
                value = str(
                    row[key_col]
                ).strip()

                if value:
                    output[value] = number

        return output

    def get_row_values(
        self,
        sheet,
        row_number,
    ):
        assert sheet == "_Author Review"
        return list(
            self.rows[row_number - 1]
        )

    def append_rows(
        self,
        sheet,
        rows,
    ):
        self.appends.append(
            (sheet, rows)
        )

    def batch_update_rows(
        self,
        sheet,
        updates,
    ):
        self.updates.append(
            (sheet, updates)
        )


def test_aggregates_same_raw_author():
    rows = build_author_review_rows(
        [
            entry(
                "A",
                "user",
                page=10,
            ),
            entry(
                "B",
                "user",
                page=11,
            ),
            entry(
                "C",
                "User",
                page=12,
            ),
        ]
    )

    assert len(rows) == 2

    lowercase = next(
        row
        for row in rows
        if row["Raw Author"] == "user"
    )

    assert (
        lowercase["Entry Count"]
        == 2
    )


def test_resolved_entries_not_queued():
    rows = build_author_review_rows(
        [
            entry(
                "A",
                "emanz",
                status="RESOLVED",
            )
        ]
    )

    assert rows == []


def test_new_review_row_is_inserted():
    sheets = FakeSheets(
        rows=[
            AUTHOR_REVIEW_HEADERS
        ]
    )

    reviews = build_author_review_rows(
        [
            entry(
                "A",
                "user",
            )
        ]
    )

    result = upsert_author_review_rows(
        sheets,
        reviews,
    )

    assert result == {
        "inserted": 1,
        "updated": 0,
    }

    assert len(sheets.appends) == 1


def test_existing_pm_decision_is_preserved():
    reviews = build_author_review_rows(
        [
            entry(
                "A",
                "user",
                content="Updated sample",
            )
        ]
    )

    existing = [
        reviews[0].get(
            header,
            "",
        )
        for header in AUTHOR_REVIEW_HEADERS
    ]

    existing[
        AUTHOR_REVIEW_HEADERS.index(
            "Decision"
        )
    ] = "APPROVE"

    existing[
        AUTHOR_REVIEW_HEADERS.index(
            "Canonical Author"
        )
    ] = "Hala Afifi"

    sheets = FakeSheets(
        rows=[
            AUTHOR_REVIEW_HEADERS,
            existing,
        ]
    )

    result = upsert_author_review_rows(
        sheets,
        reviews,
    )

    assert result == {
        "inserted": 0,
        "updated": 1,
    }

    updated = sheets.updates[0][1][0][1]

    assert updated[
        AUTHOR_REVIEW_HEADERS.index(
            "Decision"
        )
    ] == "APPROVE"

    assert updated[
        AUTHOR_REVIEW_HEADERS.index(
            "Canonical Author"
        )
    ] == "Hala Afifi"


def test_only_explicit_approval_becomes_rule():
    values = [
        AUTHOR_REVIEW_HEADERS,
        [
            "BOOK::BOOK@V1::user",
            "BOOK",
            "BOOK@V1",
            "user",
            10,
            "",
            "",
            "",
            "",
            "APPROVE",
            "Hala Afifi",
            "VERSION",
            "PM",
            "2026-10-12T20:00:00Z",
            "Confirmed",
        ],
        [
            "BOOK::BOOK@V1::User",
            "BOOK",
            "BOOK@V1",
            "User",
            5,
            "",
            "",
            "",
            "",
            "",
            "Faten Khalifeh",
            "VERSION",
            "",
            "",
            "",
        ],
    ]

    rules = (
        approved_rules_from_review_values(
            values
        )
    )

    assert len(rules) == 1

    assert (
        rules[0]["Canonical Author"]
        == "Hala Afifi"
    )

    assert (
        rules[0]["Raw Author"]
        == "user"
    )


def test_approved_review_promotes_to_author_rules():
    from author_review import (
        promote_approved_author_reviews,
    )
    from sheets_adapter import (
        AUTHOR_RULE_HEADERS,
    )

    class PromotionSheets:
        def __init__(self):
            self.appends = []

        def get_all_values(
            self,
            sheet,
        ):
            assert sheet == "_Author Review"

            return [
                AUTHOR_REVIEW_HEADERS,
                [
                    "BOOK::BOOK@V1::user",
                    "BOOK",
                    "BOOK@V1",
                    "user",
                    10,
                    "",
                    "",
                    "",
                    "",
                    "APPROVE",
                    "Hala Afifi",
                    "VERSION",
                    "PM",
                    "2026-10-12T20:00:00Z",
                    "",
                ],
            ]

        def key_to_row(
            self,
            sheet,
            key_col=0,
        ):
            assert sheet == "_Author Rules"
            return {}

        def get_row_values(
            self,
            sheet,
            row_number,
        ):
            raise AssertionError(
                "No existing rule expected."
            )

        def append_rows(
            self,
            sheet,
            rows,
        ):
            self.appends.append(
                (sheet, rows)
            )

    sheets = PromotionSheets()

    result = (
        promote_approved_author_reviews(
            sheets
        )
    )

    assert result == {
        "approved_found": 1,
        "inserted": 1,
        "existing": 0,
    }

    assert (
        sheets.appends[0][0]
        == "_Author Rules"
    )

    row = sheets.appends[0][1][0]

    rule = dict(
        zip(
            AUTHOR_RULE_HEADERS,
            row,
        )
    )

    assert (
        rule["Canonical Author"]
        == "Hala Afifi"
    )

    assert rule["Scope"] == "VERSION"


def test_existing_identical_approved_rule_is_idempotent():
    from author_review import (
        promote_approved_author_reviews,
    )
    from sheets_adapter import (
        AUTHOR_RULE_HEADERS,
    )

    review_key = "BOOK::BOOK@V1::user"
    rule_id = f"PM::{review_key}"

    existing = {
        "Rule ID": rule_id,
        "Scope": "VERSION",
        "Document Key": "BOOK",
        "Version ID": "BOOK@V1",
        "Root Entry ID": "",
        "Entry ID": "",
        "Raw Author": "user",
        "Canonical Author": "Hala Afifi",
        "Status": "APPROVED",
        "Approved By": "PM",
        "Approved At":
            "2026-10-12T20:00:00Z",
        "Notes": "",
    }

    existing_row = [
        existing.get(header, "")
        for header in AUTHOR_RULE_HEADERS
    ]

    class PromotionSheets:
        def __init__(self):
            self.appends = []

        def get_all_values(
            self,
            sheet,
        ):
            return [
                AUTHOR_REVIEW_HEADERS,
                [
                    review_key,
                    "BOOK",
                    "BOOK@V1",
                    "user",
                    10,
                    "",
                    "",
                    "",
                    "",
                    "APPROVE",
                    "Hala Afifi",
                    "VERSION",
                    "PM",
                    "2026-10-12T20:00:00Z",
                    "",
                ],
            ]

        def key_to_row(
            self,
            sheet,
            key_col=0,
        ):
            return {
                rule_id: 2,
            }

        def get_row_values(
            self,
            sheet,
            row_number,
        ):
            return existing_row

        def append_rows(
            self,
            sheet,
            rows,
        ):
            self.appends.append(
                (sheet, rows)
            )

    sheets = PromotionSheets()

    result = (
        promote_approved_author_reviews(
            sheets
        )
    )

    assert result == {
        "approved_found": 1,
        "inserted": 0,
        "existing": 1,
    }

    assert sheets.appends == []
