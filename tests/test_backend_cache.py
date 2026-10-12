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
