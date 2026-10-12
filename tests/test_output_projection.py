from sync_engine import visible_row


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


def test_visible_row_prefers_native_annotation_id():
    annotation = {
        "source_file": "book.pdf",
        "book_page": "10",
        "comment": "Change this sentence.",
        "annotation_type": "Text",
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