import pytest

from v2_pm_reply_delta import plan_reply_changes


def r(key, ids="", **fields):
    return {
        "Root Entry ID": key,
        "Reply Entry IDs": ids,
        **fields,
    }


def plan(pm, old, new):
    return plan_reply_changes(pm, old, new)


def test_no_changes():
    row = r("root")
    result = plan([row], [row], [row])
    assert result["new_reply_cell_candidates"] == []
    assert result["held_for_review"] == []


def test_new_first_reply():
    old = r("root")
    new = r("root", "reply-a", **{"Reply 1": "New reply"})
    result = plan([old], [old], [new])
    assert len(result["new_reply_cell_candidates"]) == 1
    assert result["new_reply_cell_candidates"][0]["reply_entry_id"] == "reply-a"
    assert result["google_write_operations"] == []


def test_second_reply_preserves_existing_display():
    old = r("root", "reply-a", **{"Reply 1": "Canonical"})
    pm = r("root", "reply-a", **{"Reply 1": "PM legacy format"})
    new = r(
        "root", "reply-a, reply-b",
        **{"Reply 1": "Canonical", "Reply 2": "New"}
    )
    result = plan([pm], [old], [new])
    assert [x["field"] for x in result["new_reply_cell_candidates"]] == [
        "Reply 2"
    ]


def test_pipe_separator_matches_comma_separator():
    old = r("root", "a, b", **{"Reply 1": "A", "Reply 2": "B"})
    pm = r("root", "a | b", **{"Reply 1": "PM A", "Reply 2": "PM B"})
    new = r(
        "root", "a, b, c",
        **{"Reply 1": "A", "Reply 2": "B", "Reply 3": "C"}
    )
    result = plan([pm], [old], [new])
    assert len(result["new_reply_cell_candidates"]) == 1
    assert result["new_reply_cell_candidates"][0]["field"] == "Reply 3"


def test_existing_reply_edit_is_held():
    old = r("root", "a", **{"Reply 1": "Old"})
    new = r("root", "a", **{"Reply 1": "Edited"})
    result = plan([old], [old], [new])
    assert result["new_reply_cell_candidates"] == []
    assert result["held_for_review"][0]["reason"] == (
        "EXISTING_REPLY_EDIT_REQUIRES_VERIFICATION"
    )


def test_reply_reordering_is_held():
    old = r("root", "a, b")
    new = r("root", "b, a")
    result = plan([old], [old], [new])
    assert result["held_for_review"][0]["reason"] == (
        "REPLY_REMOVAL_OR_REORDER"
    )


def test_changed_previous_reply_blocks_append():
    old = r("root", "a", **{"Reply 1": "Original"})
    new = r(
        "root", "a, b",
        **{"Reply 1": "Edited", "Reply 2": "New"}
    )
    result = plan([old], [old], [new])
    assert result["new_reply_cell_candidates"] == []
    assert result["held_for_review"][0]["reason"] == (
        "OLD_REPLY_CHANGED_WHILE_APPENDING"
    )


def test_occupied_new_reply_slot_is_held():
    old = r("root")
    pm = r("root", **{"Reply 1": "Manual value"})
    new = r("root", "a", **{"Reply 1": "New"})
    result = plan([pm], [old], [new])
    assert result["held_for_review"][0]["reason"] == (
        "NEW_REPLY_TARGET_CONFLICT"
    )


def test_conflicting_existing_ids_are_held():
    old = r("root", "a")
    pm = r("root", "different")
    new = r("root", "a, b", **{"Reply 2": "New"})
    result = plan([pm], [old], [new])
    assert result["held_for_review"][0]["reason"] == (
        "PM_REPLY_ID_BASELINE_CONFLICT"
    )


def test_duplicate_reply_across_roots_is_rejected():
    rows = [r("root1", "a"), r("root2", "a")]
    with pytest.raises(ValueError):
        plan(rows, rows, rows)


def test_no_deletion_when_reply_removed():
    old = r("root", "a", **{"Reply 1": "Old"})
    new = r("root")
    result = plan([old], [old], [new])
    assert result["deletion_operations"] == []
    assert result["held_for_review"]
