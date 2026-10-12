from author_resolution import AuthorRule
from v2_model import (
    prepare_v2_entries,
    v2_author_summary,
)


SHA = "8" * 64


def extracted(
    entry_id: str,
    raw_author: str,
):
    return {
        "entry_id": entry_id,
        "raw_author": raw_author,
        "pdf_page": 10,
        "book_page": "2",
        "annotation_type": "Text",
        "relation_type": "ROOT",
        "entry_type": "COMMENT",
        "parent_entry_id": "",
        "root_entry_id": entry_id,
        "reply_depth": 0,
        "comment": "test",
    }


def test_prepare_adds_document_and_version():
    rows = prepare_v2_entries(
        [
            extracted(
                "A",
                "emanz",
            )
        ],
        "IGCSE_ARABIC_2P",
        SHA,
    )

    assert (
        rows[0]["document_key"]
        == "IGCSE_ARABIC_2P"
    )

    assert (
        rows[0]["version_id"]
        == "IGCSE_ARABIC_2P@" + SHA
    )


def test_distinctive_alias_resolves():
    rules = [
        AuthorRule(
            rule_id="EMAN",
            scope="GLOBAL_ALIAS",
            raw_author="emanz",
            canonical_author="Eman Zahran",
        )
    ]

    rows = prepare_v2_entries(
        [
            extracted(
                "A",
                "emanz",
            )
        ],
        "IGCSE_ARABIC_2P",
        SHA,
        author_rules=rules,
    )

    assert (
        rows[0]["canonical_author"]
        == "Eman Zahran"
    )

    assert (
        rows[0]["author_status"]
        == "RESOLVED"
    )


def test_version_rule_resolves_User_only():
    version_id = (
        "IGCSE_ARABIC_2P@"
        + SHA
    )

    rules = [
        AuthorRule(
            rule_id="FATEN",
            scope="VERSION",
            version_id=version_id,
            raw_author="User",
            canonical_author=(
                "Faten Khalifeh"
            ),
        )
    ]

    rows = prepare_v2_entries(
        [
            extracted(
                "A",
                "User",
            ),
            extracted(
                "B",
                "user",
            ),
        ],
        "IGCSE_ARABIC_2P",
        SHA,
        author_rules=rules,
    )

    assert (
        rows[0]["canonical_author"]
        == "Faten Khalifeh"
    )

    assert (
        rows[1]["author_status"]
        == "UNRESOLVED"
    )


def test_historical_native_id_resolves_author():
    rows = prepare_v2_entries(
        [
            extracted(
                "HALA-ID",
                "user",
            )
        ],
        "IGCSE_ARABIC_2P",
        SHA,
        historical_author_by_entry_id={
            "HALA-ID": "Hala Afifi",
        },
    )

    assert (
        rows[0]["canonical_author"]
        == "Hala Afifi"
    )

    assert (
        rows[0][
            "author_resolution_method"
        ]
        == "HISTORICAL_NATIVE_ID"
    )


def test_duplicate_entry_id_fails():
    item = extracted(
        "A",
        "User",
    )

    try:
        prepare_v2_entries(
            [item, item],
            "IGCSE_ARABIC_2P",
            SHA,
        )
    except ValueError as exc:
        assert "duplicate entry_id" in str(
            exc
        )
    else:
        raise AssertionError(
            "Expected duplicate failure"
        )


def test_author_summary():
    rules = [
        AuthorRule(
            rule_id="EMAN",
            scope="GLOBAL_ALIAS",
            raw_author="emanz",
            canonical_author="Eman Zahran",
        )
    ]

    rows = prepare_v2_entries(
        [
            extracted(
                "A",
                "emanz",
            ),
            extracted(
                "B",
                "User",
            ),
        ],
        "IGCSE_ARABIC_2P",
        SHA,
        author_rules=rules,
    )

    summary = v2_author_summary(
        rows
    )

    assert summary["total"] == 2
    assert summary["resolved"] == 1
    assert summary["unresolved"] == 1
