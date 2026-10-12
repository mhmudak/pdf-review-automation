from sheets_adapter import VISIBLE_HEADERS
from sync_engine import (
    _database_visible_row,
    _legacy_annotation_type_e_row,
    _legacy_eman_row,
    _merge_visible_row,
    _legacy_visible_key,
    visible_row,
)

def test_legacy_visible_key_normalizes_whitespace():
    row = [
        "book.pdf",
        "link",
        "52",
        "  خطأ   لغوي  ",
        "Linguistic",
        "Osama",
        "",
        "",
        "No",
        "",
        "AAAC123",
        "",
    ]

    assert _legacy_visible_key(
        row
    ) == (
        "52",
        "خطأ لغوي",
    )

def test_legacy_match_can_replace_old_comment_id():
    existing = [
        "",
        "old-link",
        "52",
        "خطأ لغوي",
        "Linguistic",
        "Osama",
        "old-created",
        "old-modified",
        "Yes",
        "Reviewed",
        "AAAC-old-id",
        "",
    ]

    desired = [
        "book.pdf",
        "new-link",
        "52",
        "خطأ لغوي",
        "",
        "Osama Elamrety",
        "new-created",
        "new-modified",
        "",
        "",
        "canonical-uuid",
        "Highlight",
    ]

    merged = _merge_visible_row(
        desired,
        existing,
    )

    assert merged[4] == "Linguistic"
    assert merged[8] == "Yes"
    assert merged[9] == "Reviewed"
    assert merged[10] == "canonical-uuid"
    assert merged[11] == "Highlight"

def test_visible_row_falls_back_to_identity_key():
    annotation = {
        "source_file": "book.pdf",
        "book_page": "10",
        "comment": "Change this sentence.",
        "annotation_type": "Text",
        "reviewer": "Reviewer Name",
        "created": "2026-10-12T10:00:00",
        "modified": "2026-10-12T10:10:00",
        "annotation_id": "",
        "identity_key": "fallback-key-123",
    }

    row = visible_row(
        annotation,
        "https://drive.google.com/example",
    )

    assert row[10] == "fallback-key-123"
    assert row[11] == "Text"


def test_visible_row_prefers_native_annotation_id():
    annotation = {
        "source_file": "book.pdf",
        "book_page": "10",
        "comment": "Change this sentence.",
        "annotation_type": "Highlight",
        "reviewer": "Reviewer Name",
        "created": "2026-10-12T10:00:00",
        "modified": "2026-10-12T10:10:00",
        "annotation_id": "native-id-123",
        "identity_key": "fallback-key-123",
    }

    row = visible_row(
        annotation,
        "https://drive.google.com/example",
    )

    assert row[10] == "native-id-123"
    assert row[11] == "Highlight"


def test_visible_row_category_is_separate_from_annotation_type():
    annotation = {
        "source_file": "book.pdf",
        "book_page": "10",
        "comment": "Change this sentence.",
        "category": "Linguistic",
        "annotation_type": "Highlight",
        "reviewer": "Reviewer Name",
        "created": "created",
        "modified": "modified",
        "annotation_id": "id-1",
        "identity_key": "fallback",
    }

    row = visible_row(
        annotation,
        "link",
    )

    assert row[4] == "Linguistic"
    assert row[11] == "Highlight"


def test_visible_schema_keeps_category_and_hidden_technical_columns():
    assert VISIBLE_HEADERS == [
        "PDF Name",
        "PDF Drive Link",
        "Page",
        "Comment",
        "Category",
        "Author",
        "Created Date",
        "Last Modified",
        "Resolved?",
        "Replies",
        "Comment ID",
        "Annotation Type",
    ]

    assert VISIBLE_HEADERS[4] == "Category"
    assert VISIBLE_HEADERS[6] == "Created Date"
    assert VISIBLE_HEADERS[7] == "Last Modified"
    assert VISIBLE_HEADERS[10] == "Comment ID"
    assert VISIBLE_HEADERS[11] == "Annotation Type"


def test_legacy_eman_row_is_migrated():
    old = [
        "book.pdf",
        "link",
        "10",
        "comment",
        "Eman",
        "created",
        "modified",
        "Yes",
        "reply",
        "id-1",
        "Highlight",
    ]

    new = _legacy_eman_row(
        old
    )

    assert new == [
        "book.pdf",
        "link",
        "10",
        "comment",
        "",
        "Eman",
        "created",
        "modified",
        "Yes",
        "reply",
        "id-1",
        "Highlight",
    ]


def test_previous_annotation_type_e_schema_is_migrated():
    old = [
        "book.pdf",
        "link",
        "10",
        "comment",
        "Caret",
        "Reviewer",
        "created",
        "modified",
        "No",
        "reply",
        "id-2",
    ]

    new = _legacy_annotation_type_e_row(
        old
    )

    assert new == [
        "book.pdf",
        "link",
        "10",
        "comment",
        "",
        "Reviewer",
        "created",
        "modified",
        "No",
        "reply",
        "id-2",
        "Caret",
    ]


def test_database_row_projects_category_and_annotation_type_separately():
    row = [""] * 26

    row[0] = "identity-key"
    row[1] = "Osama Elamrety"
    row[3] = "book.pdf"
    row[5] = "drive-link"
    row[8] = "44"
    row[11] = "Text"
    row[12] = "Linguistic"
    row[13] = "Fix wording"
    row[15] = "created"
    row[16] = "modified"
    row[17] = "annotation-123"

    visible = _database_visible_row(
        row
    )

    assert visible == [
        "book.pdf",
        "drive-link",
        "44",
        "Fix wording",
        "Linguistic",
        "Osama Elamrety",
        "created",
        "modified",
        "",
        "",
        "annotation-123",
        "Text",
    ]


def test_merge_preserves_manual_fields_and_existing_category():
    desired = [
        "book.pdf",
        "link",
        "10",
        "updated comment",
        "",
        "Reviewer",
        "created-new",
        "modified-new",
        "",
        "",
        "id-3",
        "Highlight",
    ]

    existing = [
        "book.pdf",
        "link",
        "10",
        "old comment",
        "Content",
        "Reviewer",
        "created-old",
        "modified-old",
        "Yes",
        "PM reply",
        "id-3",
        "Highlight",
    ]

    merged = _merge_visible_row(
        desired,
        existing,
    )

    assert merged[3] == "updated comment"
    assert merged[4] == "Content"
    assert merged[8] == "Yes"
    assert merged[9] == "PM reply"
    assert merged[10] == "id-3"
    assert merged[11] == "Highlight"
