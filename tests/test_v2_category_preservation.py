import pytest

from v2_change_planner import PlannedEntryChange, V2ChangePlan
from v2_mutations import build_v2_mutations


def make_mutations(
    change_type,
    previous_category,
    current_category=None,
):
    current = {
        "entry_id": "COMMENT-1",
        "entry_signature": "new-signature",
        "comment": "Updated PDF comment",
    }

    if current_category is not None:
        current["category"] = current_category

    previous = {
        "Entry ID": "COMMENT-1",
        "Entry Signature": "old-signature",
        "Category": previous_category,
        "First Seen": "2026-10-01",
    }

    change = PlannedEntryChange(
        change_type=change_type,
        document_key="TEST_DOCUMENT",
        entry_id="COMMENT-1",
        current=current,
        previous=previous,
    )

    plan = V2ChangePlan(
        document_key="TEST_DOCUMENT",
        changes=(change,),
    )

    return build_v2_mutations(
        plan,
        recorded_at="2026-10-13T12:00:00+00:00",
    )


@pytest.mark.parametrize(
    "change_type",
    ["UPDATED", "AUTHOR_UPDATED"],
)
def test_existing_category_survives_blank_update(change_type):
    mutations = make_mutations(
        change_type,
        previous_category="Language",
        current_category="",
    )

    assert mutations.update_entries[0]["Category"] == "Language"


def test_existing_category_survives_missing_category():
    mutations = make_mutations(
        "UPDATED",
        previous_category="Content",
    )

    assert mutations.update_entries[0]["Category"] == "Content"


def test_explicit_new_category_replaces_existing():
    mutations = make_mutations(
        "UPDATED",
        previous_category="Language",
        current_category="Design",
    )

    assert mutations.update_entries[0]["Category"] == "Design"


def test_existing_category_survives_whitespace():
    mutations = make_mutations(
        "UPDATED",
        previous_category="Content",
        current_category="   ",
    )

    assert mutations.update_entries[0]["Category"] == "Content"


def test_unchanged_entry_generates_no_mutation():
    mutations = make_mutations(
        "UNCHANGED",
        previous_category="Language",
        current_category="",
    )

    assert not mutations.insert_entries
    assert not mutations.update_entries
    assert not mutations.deactivate_entries
    assert not mutations.history_rows
