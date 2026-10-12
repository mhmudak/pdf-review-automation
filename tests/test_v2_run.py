from backend_cache import BackendSnapshot
from v2_run import prepare_v2_run


SHA = "a" * 64
NOW = "2026-10-12T20:00:00+00:00"


def empty_snapshot():
    return BackendSnapshot(
        documents=[],
        files=[],
        entries=[],
        author_rules=[],
    )


def extracted(
    entry_id,
    raw_author,
    content="Hello",
):
    return {
        "entry_id": entry_id,
        "raw_author": raw_author,
        "content": content,
        "comment": content,
        "entry_type": "COMMENT",
        "relation_type": "ROOT",
        "reply_depth": 0,
        "pdf_page": 1,
        "book_page": 1,
        "annotation_type": "Text",
        "created": "",
        "modified": "",
        "coordinates": "",
        "xref": 10,
    }


def test_prepare_v2_run_resolves_config_alias():
    run = prepare_v2_run(
        snapshot=empty_snapshot(),
        config={
            "reviewer_aliases": {
                "emanz":
                    "Eman Zahran",
            }
        },
        extracted_rows=[
            extracted(
                "A",
                "emanz",
            )
        ],
        summary={
            "pages": 323,
            "entries_found": 1,
        },
        document_key=(
            "IGCSE_ARABIC_2P"
        ),
        sha256=SHA,
        drive_file_id="drive-1",
        pdf_name="trial.pdf",
        drive_link="https://example.test",
        modified_time=(
            "2026-10-12T19:00:00Z"
        ),
        size_bytes=123,
        master_version="MASTER-1",
        processed_at=NOW,
    )

    assert len(run.entries) == 1

    entry = run.entries[0]

    assert (
        entry["canonical_author"]
        == "Eman Zahran"
    )

    assert (
        entry["author_status"]
        == "RESOLVED"
    )

    assert (
        run.change_plan.counts()[
            "NEW"
        ]
        == 1
    )

    assert (
        run.version_row[
            "Version Status"
        ]
        == "PROCESSED"
    )


def test_generic_user_remains_reviewable():
    run = prepare_v2_run(
        snapshot=empty_snapshot(),
        config={
            "reviewer_aliases": {
                "user": "Hala Afifi",
            }
        },
        extracted_rows=[
            extracted(
                "A",
                "user",
            )
        ],
        summary={
            "pages": 323,
            "entries_found": 1,
        },
        document_key=(
            "IGCSE_ARABIC_2P"
        ),
        sha256=SHA,
        drive_file_id="drive-1",
        pdf_name="trial.pdf",
        drive_link="",
        modified_time="",
        size_bytes=123,
        processed_at=NOW,
    )

    entry = run.entries[0]

    assert (
        entry["author_status"]
        != "RESOLVED"
    )

    assert (
        run.version_row[
            "Version Status"
        ]
        == "NEEDS_AUTHOR_REVIEW"
    )

    assert (
        run.document_row[
            "Status"
        ]
        == "NEEDS_AUTHOR_REVIEW"
    )


def test_historical_native_id_resolves_generic_user():
    run = prepare_v2_run(
        snapshot=empty_snapshot(),
        config={},
        extracted_rows=[
            extracted(
                "HALA-ID-1",
                "user",
            )
        ],
        summary={
            "pages": 323,
            "entries_found": 1,
        },
        document_key=(
            "IGCSE_ARABIC_2P"
        ),
        sha256=SHA,
        drive_file_id="drive-1",
        pdf_name="trial.pdf",
        drive_link="",
        modified_time="",
        size_bytes=123,
        historical_author_by_entry_id={
            "HALA-ID-1":
                "Hala Afifi",
        },
        processed_at=NOW,
    )

    entry = run.entries[0]

    assert (
        entry["canonical_author"]
        == "Hala Afifi"
    )

    assert (
        entry[
            "author_resolution_method"
        ]
        == "HISTORICAL_NATIVE_ID"
    )

    assert (
        run.version_row[
            "Version Status"
        ]
        == "PROCESSED"
    )


def test_pm_version_rule_resolves_capital_user():
    from versioning import make_version_id

    version_id = make_version_id(
        "IGCSE_ARABIC_2P",
        SHA,
    )

    snapshot = BackendSnapshot(
        documents=[],
        files=[],
        entries=[],
        author_rules=[
            {
                "Rule ID":
                    "PM-FATEN-1",
                "Scope": "VERSION",
                "Document Key":
                    "IGCSE_ARABIC_2P",
                "Version ID":
                    version_id,
                "Raw Author": "User",
                "Canonical Author":
                    "Faten Khalifeh",
                "Status": "APPROVED",
            }
        ],
    )

    run = prepare_v2_run(
        snapshot=snapshot,
        config={},
        extracted_rows=[
            extracted(
                "FATEN-ID-1",
                "User",
            )
        ],
        summary={
            "pages": 323,
            "entries_found": 1,
        },
        document_key=(
            "IGCSE_ARABIC_2P"
        ),
        sha256=SHA,
        drive_file_id="drive-1",
        pdf_name="trial.pdf",
        drive_link="",
        modified_time="",
        size_bytes=123,
        processed_at=NOW,
    )

    entry = run.entries[0]

    assert (
        entry["canonical_author"]
        == "Faten Khalifeh"
    )

    assert (
        entry["author_rule_id"]
        == "PM-FATEN-1"
    )
