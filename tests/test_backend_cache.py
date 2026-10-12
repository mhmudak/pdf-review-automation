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
                "SHA256": "abc",
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
        "_Files": [
            [
                "Document Key",
                "SHA256",
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
