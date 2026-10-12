from backend_cache import BackendSnapshot


def snapshot():
    return BackendSnapshot(
        documents=[
            {
                "Document Key": "DOC1",
                "Current Version ID": "V1",
            }
        ],
        files=[
            {
                "Document Key": "DOC1",
                "PDF SHA256": "abc",
            }
        ],
        entries=[
            {
                "Document Key": "DOC1",
                "Entry ID": "A",
            },
            {
                "Document Key": "DOC1",
                "Entry ID": "B",
            },
            {
                "Document Key": "DOC2",
                "Entry ID": "C",
            },
        ],
        author_rules=[],
    )


def test_document_lookup():
    s = snapshot()

    assert (
        s.document("DOC1")[
            "Current Version ID"
        ]
        == "V1"
    )


def test_entries_for_document():
    s = snapshot()

    ids = {
        row["Entry ID"]
        for row in s.entries_for_document(
            "DOC1"
        )
    }

    assert ids == {"A", "B"}


def test_entry_lookup():
    s = snapshot()

    assert (
        s.entry("C")[
            "Document Key"
        ]
        == "DOC2"
    )


def test_known_sha():
    s = snapshot()

    assert s.sha_known(
        "DOC1",
        "ABC",
    )


def test_unknown_sha():
    s = snapshot()

    assert not s.sha_known(
        "DOC1",
        "def",
    )


def test_rows_to_dicts():
    from backend_cache import rows_to_dicts

    values = [
        [
            "Document Key",
            "Entry ID",
            "Active",
        ],
        [
            "DOC1",
            "A",
            True,
        ],
        [
            "DOC1",
            "B",
        ],
    ]

    rows = rows_to_dicts(values)

    assert rows == [
        {
            "Document Key": "DOC1",
            "Entry ID": "A",
            "Active": True,
        },
        {
            "Document Key": "DOC1",
            "Entry ID": "B",
            "Active": "",
        },
    ]


def test_snapshot_from_batch_values():
    from backend_cache import (
        snapshot_from_batch_values,
    )

    batch = {
        "_Documents": [
            [
                "Document Key",
                "Current Version ID",
            ],
            [
                "DOC1",
                "V1",
            ],
        ],
        "_Versions": [
            [
                "Document Key",
                "PDF SHA256",
            ],
            [
                "DOC1",
                "abc",
            ],
        ],
        "_Entries_V2": [
            [
                "Document Key",
                "Entry ID",
            ],
            [
                "DOC1",
                "A",
            ],
        ],
        "_Author Rules": [
            [
                "Rule ID",
                "Status",
            ],
            [
                "R1",
                "APPROVED",
            ],
        ],
    }

    snapshot = (
        snapshot_from_batch_values(
            batch
        )
    )

    assert (
        snapshot.document("DOC1")[
            "Current Version ID"
        ]
        == "V1"
    )

    assert snapshot.sha_known(
        "DOC1",
        "ABC",
    )

    assert (
        snapshot.entry("A")[
            "Document Key"
        ]
        == "DOC1"
    )

    assert (
        snapshot.author_rules[0][
            "Rule ID"
        ]
        == "R1"
    )


def test_entry_for_document_uses_composite_identity():
    snapshot = BackendSnapshot(
        documents=[],
        files=[],
        entries=[
            {
                "Document Key": "BOOK-A",
                "Entry ID": "UUID-1",
                "Content": "A",
            },
            {
                "Document Key": "BOOK-B",
                "Entry ID": "UUID-1",
                "Content": "B",
            },
        ],
        author_rules=[],
    )

    assert (
        snapshot.entry_for_document(
            "BOOK-A",
            "UUID-1",
        )["Content"]
        == "A"
    )

    assert (
        snapshot.entry_for_document(
            "BOOK-B",
            "UUID-1",
        )["Content"]
        == "B"
    )


def test_ambiguous_global_entry_lookup_fails_closed():
    import pytest

    snapshot = BackendSnapshot(
        documents=[],
        files=[],
        entries=[
            {
                "Document Key": "BOOK-A",
                "Entry ID": "UUID-1",
            },
            {
                "Document Key": "BOOK-B",
                "Entry ID": "UUID-1",
            },
        ],
        author_rules=[],
    )

    with pytest.raises(
        ValueError,
        match="ambiguous",
    ):
        snapshot.entry(
            "UUID-1"
        )


def test_duplicate_canonical_entry_fails_closed():
    import pytest

    with pytest.raises(
        ValueError,
        match="Duplicate canonical entry",
    ):
        BackendSnapshot(
            documents=[],
            files=[],
            entries=[
                {
                    "Document Key": "BOOK",
                    "Entry ID": "UUID-1",
                },
                {
                    "Document Key": "BOOK",
                    "Entry ID": "UUID-1",
                },
            ],
            author_rules=[],
        )
