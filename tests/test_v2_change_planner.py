import pytest

from backend_cache import BackendSnapshot
from v2_change_planner import plan_v2_changes


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
    document="BOOK",
):
    return {
        "document_key": document,
        "entry_id": entry_id,
        "entry_signature": signature,
        "active": True,
        "source_state": "CURRENT",
    }


def old(
    entry_id,
    signature,
    *,
    active=True,
    document="BOOK",
):
    return {
        "Document Key": document,
        "Entry ID": entry_id,
        "Entry Signature": signature,
        "Active": active,
    }


def test_new_entry():
    plan = plan_v2_changes(
        snapshot([]),
        "BOOK",
        [
            prepared(
                "A",
                "sig-a",
            )
        ],
    )

    assert plan.counts() == {
        "NEW": 1,
        "UPDATED": 0,
        "UNCHANGED": 0,
        "REMOVED": 0,
    }


def test_unchanged_entry():
    plan = plan_v2_changes(
        snapshot([
            old(
                "A",
                "sig-a",
            )
        ]),
        "BOOK",
        [
            prepared(
                "A",
                "sig-a",
            )
        ],
    )

    assert plan.counts()["UNCHANGED"] == 1


def test_changed_signature_is_updated():
    plan = plan_v2_changes(
        snapshot([
            old(
                "A",
                "old-signature",
            )
        ]),
        "BOOK",
        [
            prepared(
                "A",
                "new-signature",
            )
        ],
    )

    assert plan.counts()["UPDATED"] == 1


def test_missing_active_entry_is_removed():
    plan = plan_v2_changes(
        snapshot([
            old(
                "A",
                "sig-a",
            )
        ]),
        "BOOK",
        [],
    )

    assert plan.counts()["REMOVED"] == 1


def test_already_inactive_entry_not_removed_again():
    plan = plan_v2_changes(
        snapshot([
            old(
                "A",
                "sig-a",
                active=False,
            )
        ]),
        "BOOK",
        [],
    )

    assert plan.counts()["REMOVED"] == 0


def test_reappearing_inactive_entry_is_updated():
    plan = plan_v2_changes(
        snapshot([
            old(
                "A",
                "sig-a",
                active=False,
            )
        ]),
        "BOOK",
        [
            prepared(
                "A",
                "sig-a",
            )
        ],
    )

    assert plan.counts()["UPDATED"] == 1


def test_mixed_version():
    plan = plan_v2_changes(
        snapshot([
            old(
                "A",
                "same",
            ),
            old(
                "B",
                "old",
            ),
            old(
                "C",
                "removed",
            ),
        ]),
        "BOOK",
        [
            prepared(
                "A",
                "same",
            ),
            prepared(
                "B",
                "new",
            ),
            prepared(
                "D",
                "brand-new",
            ),
        ],
    )

    assert plan.counts() == {
        "NEW": 1,
        "UPDATED": 1,
        "UNCHANGED": 1,
        "REMOVED": 1,
    }


def test_duplicate_prepared_entry_fails_closed():
    with pytest.raises(
        ValueError,
        match="Duplicate prepared",
    ):
        plan_v2_changes(
            snapshot([]),
            "BOOK",
            [
                prepared(
                    "A",
                    "sig-1",
                ),
                prepared(
                    "A",
                    "sig-2",
                ),
            ],
        )


def test_wrong_document_fails_closed():
    with pytest.raises(
        ValueError,
        match="different document",
    ):
        plan_v2_changes(
            snapshot([]),
            "BOOK",
            [
                prepared(
                    "A",
                    "sig",
                    document="OTHER",
                )
            ],
        )


def test_missing_signature_fails_closed():
    with pytest.raises(
        ValueError,
        match="entry_signature",
    ):
        plan_v2_changes(
            snapshot([]),
            "BOOK",
            [
                {
                    "document_key": "BOOK",
                    "entry_id": "A",
                }
            ],
        )
