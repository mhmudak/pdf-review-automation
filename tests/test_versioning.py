from versioning import (
    change_counts,
    classify_version,
    compare_versions,
    entry_signature,
    make_version_id,
)


SHA1 = "1" * 64
SHA2 = "2" * 64


def entry(
    entry_id: str,
    comment: str,
    raw_author: str = "emanz",
):
    return {
        "entry_id": entry_id,
        "raw_author": raw_author,
        "pdf_page": 10,
        "book_page": "2",
        "annotation_type": "Text",
        "relation_type": "ROOT",
        "parent_entry_id": "",
        "root_entry_id": entry_id,
        "reply_depth": 0,
        "comment": comment,
        "selected_text": "",
        "subject": "",
        "created": "2026-10-01",
        "modified": "2026-10-01",
        "rect_x0": 1,
        "rect_y0": 2,
        "rect_x1": 3,
        "rect_y1": 4,
    }


def test_version_id_is_deterministic():
    assert make_version_id(
        "IGCSE_ARABIC_2P",
        SHA1,
    ) == (
        "IGCSE_ARABIC_2P@"
        + SHA1
    )


def test_same_sha_is_duplicate():
    result = classify_version(
        "IGCSE_ARABIC_2P",
        SHA1,
        {SHA1},
    )

    assert result.action == "DUPLICATE"


def test_different_sha_is_new_version():
    result = classify_version(
        "IGCSE_ARABIC_2P",
        SHA2,
        {SHA1},
    )

    assert result.action == "NEW_VERSION"


def test_unchanged_entry():
    old = entry(
        "A",
        "same",
    )

    new = dict(old)

    changes = compare_versions(
        [old],
        [new],
    )

    assert changes[0].state == "UNCHANGED"


def test_same_id_changed_comment_is_updated():
    old = entry(
        "A",
        "old text",
    )

    new = entry(
        "A",
        "new text",
    )

    changes = compare_versions(
        [old],
        [new],
    )

    assert changes[0].state == "UPDATED"


def test_new_entry():
    changes = compare_versions(
        [],
        [
            entry(
                "A",
                "new",
            )
        ],
    )

    assert changes[0].state == "NEW"


def test_removed_entry():
    changes = compare_versions(
        [
            entry(
                "A",
                "old",
            )
        ],
        [],
    )

    assert changes[0].state == "REMOVED"


def test_author_resolution_change_does_not_change_pdf_signature():
    old = entry(
        "A",
        "same",
        raw_author="User",
    )

    old["canonical_author"] = ""
    old["author_status"] = "UNRESOLVED"

    new = dict(old)

    new["canonical_author"] = (
        "Faten Khalifeh"
    )

    new["author_status"] = "RESOLVED"
    new["author_resolution_method"] = (
        "VERSION"
    )

    assert (
        entry_signature(old)
        == entry_signature(new)
    )


def test_raw_author_change_is_pdf_update():
    old = entry(
        "A",
        "same",
        raw_author="User",
    )

    new = entry(
        "A",
        "same",
        raw_author="Faten",
    )

    assert (
        entry_signature(old)
        != entry_signature(new)
    )


def test_mixed_version_changes():
    old = [
        entry("A", "same"),
        entry("B", "before"),
        entry("C", "removed"),
    ]

    new = [
        entry("A", "same"),
        entry("B", "after"),
        entry("D", "new"),
    ]

    changes = compare_versions(
        old,
        new,
    )

    assert change_counts(
        changes
    ) == {
        "NEW": 1,
        "UPDATED": 1,
        "UNCHANGED": 1,
        "REMOVED": 1,
    }


def test_duplicate_entry_id_fails_closed():
    duplicate = entry(
        "A",
        "same",
    )

    try:
        compare_versions(
            [duplicate, duplicate],
            [],
        )
    except ValueError as exc:
        assert "duplicate previous entry_id" in str(
            exc
        )
    else:
        raise AssertionError(
            "Expected duplicate entry ID failure"
        )
