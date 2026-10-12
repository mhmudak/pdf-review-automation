from backend_cache import BackendSnapshot
from v2_change_planner import plan_v2_changes
from v2_mutations import build_v2_mutations


NOW = "2026-10-12T20:00:00+00:00"


def snapshot(entries):
    return BackendSnapshot(
        documents=[],
        files=[],
        entries=entries,
        author_rules=[],
    )


def prepared(
    entry_id,
    signature,
    *,
    version="BOOK@v2",
    content="Text",
):
    return {
        "document_key": "BOOK",
        "version_id": version,
        "entry_id": entry_id,
        "entry_signature": signature,
        "comment": content,
        "raw_author": "Luma Hameed",
        "canonical_author": "Luma Hameed",
        "author_status": "RESOLVED",
        "entry_type": "COMMENT",
        "relation_type": "ROOT",
        "active": True,
        "source_state": "CURRENT",
    }


def old(
    entry_id,
    signature,
    *,
    active=True,
    first_seen="2026-10-01T00:00:00+00:00",
):
    return {
        "Entry Key": f"BOOK::{entry_id}",
        "Document Key": "BOOK",
        "Version ID": "BOOK@v1",
        "Entry ID": entry_id,
        "Entry Signature": signature,
        "Content": "Old text",
        "Raw Author": "Luma Hameed",
        "Canonical Author": "Luma Hameed",
        "Author Status": "RESOLVED",
        "Active": active,
        "Source State": (
            "CURRENT"
            if active
            else "HISTORICAL"
        ),
        "First Seen": first_seen,
        "Last Seen": first_seen,
    }


def test_unchanged_produces_zero_mutations():
    plan = plan_v2_changes(
        snapshot([
            old("A", "sig"),
        ]),
        "BOOK",
        [
            prepared("A", "sig"),
        ],
    )

    mutations = build_v2_mutations(
        plan,
        recorded_at=NOW,
    )

    assert mutations.counts() == {
        "INSERT": 0,
        "UPDATE": 0,
        "DEACTIVATE": 0,
        "HISTORY": 0,
    }


def test_new_entry_creates_insert_and_history():
    plan = plan_v2_changes(
        snapshot([]),
        "BOOK",
        [
            prepared("A", "sig"),
        ],
    )

    mutations = build_v2_mutations(
        plan,
        recorded_at=NOW,
    )

    assert mutations.counts() == {
        "INSERT": 1,
        "UPDATE": 0,
        "DEACTIVATE": 0,
        "HISTORY": 1,
    }

    row = mutations.insert_entries[0]

    assert row["Entry Key"] == "BOOK::A"
    assert row["Entry Signature"] == "sig"
    assert row["Active"] is True
    assert row["First Seen"] == NOW
    assert row["Last Seen"] == NOW

    assert (
        mutations.history_rows[0][
            "Change Type"
        ]
        == "NEW"
    )


def test_updated_preserves_first_seen():
    first_seen = (
        "2026-09-01T00:00:00+00:00"
    )

    plan = plan_v2_changes(
        snapshot([
            old(
                "A",
                "old",
                first_seen=first_seen,
            ),
        ]),
        "BOOK",
        [
            prepared(
                "A",
                "new",
                content="Updated text",
            ),
        ],
    )

    mutations = build_v2_mutations(
        plan,
        recorded_at=NOW,
    )

    assert len(
        mutations.update_entries
    ) == 1

    row = mutations.update_entries[0]

    assert row["First Seen"] == first_seen
    assert row["Last Seen"] == NOW
    assert row["Entry Signature"] == "new"

    history = mutations.history_rows[0]

    assert history["Change Type"] == "UPDATED"
    assert history["Previous Signature"] == "old"
    assert history["Entry Signature"] == "new"


def test_removed_deactivates_without_deleting():
    plan = plan_v2_changes(
        snapshot([
            old("A", "sig"),
        ]),
        "BOOK",
        [],
    )

    mutations = build_v2_mutations(
        plan,
        recorded_at=NOW,
    )

    assert mutations.counts() == {
        "INSERT": 0,
        "UPDATE": 0,
        "DEACTIVATE": 1,
        "HISTORY": 1,
    }

    row = (
        mutations.deactivate_entries[0]
    )

    assert row["Active"] is False
    assert (
        row["Source State"]
        == "HISTORICAL"
    )
    assert row["Last Seen"] == NOW

    assert (
        mutations.history_rows[0][
            "Change Type"
        ]
        == "REMOVED"
    )


def test_mixed_version_only_writes_changes():
    plan = plan_v2_changes(
        snapshot([
            old("A", "same"),
            old("B", "old"),
            old("C", "gone"),
        ]),
        "BOOK",
        [
            prepared("A", "same"),
            prepared("B", "new"),
            prepared("D", "brand-new"),
        ],
    )

    mutations = build_v2_mutations(
        plan,
        recorded_at=NOW,
    )

    assert mutations.counts() == {
        "INSERT": 1,
        "UPDATE": 1,
        "DEACTIVATE": 1,
        "HISTORY": 3,
    }


def test_author_update_writes_canonical_and_history():
    previous = old(
        "A",
        "same-signature",
    )

    previous.update(
        {
            "Canonical Author": "",
            "Author Status": "NEEDS_REVIEW",
            "Author Resolution Method": "UNRESOLVED",
            "Author Rule ID": "",
        }
    )

    current = prepared(
        "A",
        "same-signature",
    )

    current.update(
        {
            "canonical_author": "Hala Afifi",
            "author_status": "RESOLVED",
            "author_resolution_method": "ENTRY_RULE",
            "author_rule_id": "R-HALA-001",
        }
    )

    plan = plan_v2_changes(
        snapshot([previous]),
        "BOOK",
        [current],
    )

    mutations = build_v2_mutations(
        plan,
        recorded_at=NOW,
    )

    assert mutations.counts() == {
        "INSERT": 0,
        "UPDATE": 1,
        "DEACTIVATE": 0,
        "HISTORY": 1,
    }

    assert (
        mutations.update_entries[0][
            "Canonical Author"
        ]
        == "Hala Afifi"
    )

    assert (
        mutations.history_rows[0][
            "Change Type"
        ]
        == "AUTHOR_UPDATED"
    )

    assert (
        mutations.history_rows[0][
            "Previous Signature"
        ]
        == "same-signature"
    )
