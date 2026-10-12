from extractor import (
    classify_relation,
    resolve_annotation_hierarchy,
)


def test_no_parent_is_root():
    assert (
        classify_relation(
            0,
            "",
        )
        == "ROOT"
    )


def test_irt_group_is_group():
    assert (
        classify_relation(
            123,
            "/Group",
        )
        == "GROUP"
    )


def test_irt_without_group_is_reply():
    assert (
        classify_relation(
            123,
            "",
        )
        == "REPLY"
    )


def test_reply_to_root():
    rows = [
        {
            "xref": 10,
            "entry_id": "C1",
            "parent_xref": 0,
            "relation_type": "ROOT",
        },
        {
            "xref": 11,
            "entry_id": "R1",
            "parent_xref": 10,
            "relation_type": "REPLY",
        },
    ]

    resolve_annotation_hierarchy(rows)

    assert (
        rows[0]["entry_type"]
        == "COMMENT"
    )

    assert (
        rows[0]["root_entry_id"]
        == "C1"
    )

    assert (
        rows[0]["reply_depth"]
        == 0
    )

    assert (
        rows[1]["entry_type"]
        == "REPLY"
    )

    assert (
        rows[1]["parent_entry_id"]
        == "C1"
    )

    assert (
        rows[1]["root_entry_id"]
        == "C1"
    )

    assert (
        rows[1]["reply_depth"]
        == 1
    )


def test_nested_reply():
    rows = [
        {
            "xref": 10,
            "entry_id": "C1",
            "parent_xref": 0,
            "relation_type": "ROOT",
        },
        {
            "xref": 11,
            "entry_id": "R1",
            "parent_xref": 10,
            "relation_type": "REPLY",
        },
        {
            "xref": 12,
            "entry_id": "R2",
            "parent_xref": 11,
            "relation_type": "REPLY",
        },
    ]

    resolve_annotation_hierarchy(rows)

    assert (
        rows[2]["parent_entry_id"]
        == "R1"
    )

    assert (
        rows[2]["root_entry_id"]
        == "C1"
    )

    assert (
        rows[2]["reply_depth"]
        == 2
    )


def test_group_relation_is_not_reply():
    rows = [
        {
            "xref": 20,
            "entry_id": "C1",
            "parent_xref": 0,
            "relation_type": "ROOT",
        },
        {
            "xref": 21,
            "entry_id": "G1",
            "parent_xref": 20,
            "relation_type": "GROUP",
        },
    ]

    resolve_annotation_hierarchy(rows)

    assert (
        rows[1]["parent_entry_id"]
        == "C1"
    )

    assert (
        rows[1]["entry_type"]
        == "COMMENT"
    )

    assert (
        rows[1]["relation_type"]
        == "GROUP"
    )

    assert (
        rows[1]["reply_depth"]
        == 0
    )


def test_missing_reply_parent_does_not_crash():
    rows = [
        {
            "xref": 30,
            "entry_id": "R1",
            "parent_xref": 999,
            "relation_type": "REPLY",
        }
    ]

    resolve_annotation_hierarchy(rows)

    assert (
        rows[0]["entry_type"]
        == "REPLY"
    )

    assert (
        rows[0]["parent_entry_id"]
        == ""
    )

    assert (
        rows[0]["root_entry_id"]
        == ""
    )

    assert (
        rows[0]["reply_depth"]
        == 1
    )