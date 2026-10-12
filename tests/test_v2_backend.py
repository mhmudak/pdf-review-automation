from v2_backend import (
    V2_SNAPSHOT_SHEETS,
    ensure_v2_backend,
    load_v2_snapshot,
)


class FakeSheets:
    def __init__(self):
        self.ensure_calls = []
        self.batch_calls = []

    def ensure_headers(
        self,
        sheet,
        headers,
    ):
        self.ensure_calls.append(
            (
                sheet,
                list(headers),
            )
        )

    def batch_get_values(
        self,
        sheets,
        refresh=False,
    ):
        self.batch_calls.append(
            (
                list(sheets),
                refresh,
            )
        )

        return {
            "_Documents": [
                [
                    "Document Key",
                    "Current Version ID",
                ],
                [
                    "BOOK",
                    "BOOK@v2",
                ],
            ],
            "_Versions": [
                [
                    "Document Key",
                    "PDF SHA256",
                ],
                [
                    "BOOK",
                    "abc123",
                ],
            ],
            "_Entries_V2": [
                [
                    "Document Key",
                    "Entry ID",
                    "Entry Signature",
                ],
                [
                    "BOOK",
                    "A",
                    "sig-a",
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


def test_v2_snapshot_sheet_set():
    assert V2_SNAPSHOT_SHEETS == [
        "_Documents",
        "_Versions",
        "_Entries_V2",
        "_Author Rules",
    ]


def test_load_v2_snapshot_uses_one_batch_call():
    sheets = FakeSheets()

    snapshot = load_v2_snapshot(
        sheets
    )

    assert sheets.batch_calls == [
        (
            V2_SNAPSHOT_SHEETS,
            False,
        )
    ]

    assert (
        snapshot.document("BOOK")[
            "Current Version ID"
        ]
        == "BOOK@v2"
    )

    assert snapshot.sha_known(
        "BOOK",
        "ABC123",
    )

    assert (
        snapshot.entry_for_document(
            "BOOK",
            "A",
        )["Entry Signature"]
        == "sig-a"
    )


def test_ensure_v2_backend_has_five_schemas():
    sheets = FakeSheets()

    ensure_v2_backend(
        sheets
    )

    assert [
        name
        for name, _ in sheets.ensure_calls
    ] == [
        "_Documents",
        "_Versions",
        "_Entries_V2",
        "_Entry History",
        "_Author Rules",
    ]


def test_author_rules_from_snapshot():
    from backend_cache import BackendSnapshot
    from v2_backend import (
        author_rules_from_snapshot,
    )

    snapshot = BackendSnapshot(
        documents=[],
        files=[],
        entries=[],
        author_rules=[
            {
                "Rule ID": "R1",
                "Scope": "VERSION",
                "Version ID": "BOOK@abc",
                "Raw Author": "User",
                "Canonical Author":
                    "Faten Khalifeh",
                "Status": "APPROVED",
            }
        ],
    )

    rules = author_rules_from_snapshot(
        snapshot
    )

    assert len(rules) == 1
    assert rules[0].rule_id == "R1"
    assert rules[0].scope == "VERSION"
    assert (
        rules[0].canonical_author
        == "Faten Khalifeh"
    )
    assert rules[0].raw_author == "User"


def test_config_alias_rules_skip_generic_authors():
    from v2_backend import config_alias_rules

    rules = config_alias_rules(
        {
            "reviewer_aliases": {
                "Luma Hameed":
                    "Luma Hameed",
                "emanz":
                    "Eman Zahran",
                "S.A.I.D..F.A.R.H.A.T":
                    "Said Farhat",
                "User":
                    "Faten Khalifeh",
                "user":
                    "Hala Afifi",
            }
        }
    )

    by_raw = {
        rule.raw_author:
            rule.canonical_author
        for rule in rules
    }

    assert by_raw == {
        "Luma Hameed":
            "Luma Hameed",
        "emanz":
            "Eman Zahran",
        "S.A.I.D..F.A.R.H.A.T":
            "Said Farhat",
    }

    assert "User" not in by_raw
    assert "user" not in by_raw


def test_effective_rules_include_config_and_pm_rules():
    from backend_cache import BackendSnapshot
    from v2_backend import effective_author_rules

    snapshot = BackendSnapshot(
        documents=[],
        files=[],
        entries=[],
        author_rules=[
            {
                "Rule ID": "PM-FATEN-1",
                "Scope": "VERSION",
                "Version ID":
                    "IGCSE_ARABIC_2P@version",
                "Raw Author": "User",
                "Canonical Author":
                    "Faten Khalifeh",
                "Status": "APPROVED",
            }
        ],
    )

    rules = effective_author_rules(
        snapshot,
        {
            "reviewer_aliases": {
                "emanz":
                    "Eman Zahran",
            }
        },
    )

    assert len(rules) == 2

    assert any(
        rule.scope == "GLOBAL_ALIAS"
        and rule.raw_author == "emanz"
        and rule.canonical_author
            == "Eman Zahran"
        for rule in rules
    )

    assert any(
        rule.rule_id == "PM-FATEN-1"
        and rule.scope == "VERSION"
        and rule.raw_author == "User"
        for rule in rules
    )
