import pytest

from v2_pm_cell_plan import PM_HEADER_SEQUENCE
from v2_pm_combined_plan import plan_verified_pm_cells


ROOT = "root-1"


def pm(comment="Original", replies=(), ids="", category="Manual"):
    row = [""] * 22
    row[4] = comment
    row[8] = category
    row[14] = ROOT
    row[21] = ids
    for i, value in enumerate(replies):
        row[5 + i] = value
    return [list(PM_HEADER_SEQUENCE), row]


def source(comment="Original", replies=(), ids=""):
    row = {
        "Root Entry ID": ROOT,
        "Comment": comment,
        "Reply Entry IDs": ids,
    }
    for i, value in enumerate(replies, 1):
        row[f"Reply {i}"] = value
    return [row]


def run(sheet, before, after):
    return plan_verified_pm_cells(sheet, before, after)


def test_no_change_is_noop():
    result = run(pm(), source(), source())
    assert result["blockers"] == []
    assert result["cell_update_candidates"] == []


def test_verified_comment_edit():
    result = run(
        pm(),
        source(),
        source(comment="Revised"),
    )
    assert result["blockers"] == []
    assert [x["cell"] for x in result["cell_update_candidates"]] == [
        "E2"
    ]


def test_new_reply_updates_text_and_ids():
    before = source(
        replies=("Original reply",),
        ids="reply-a",
    )
    after = source(
        replies=("Original reply", "New reply"),
        ids="reply-a | reply-b",
    )
    result = run(
        pm(
            replies=("Original reply",),
            ids="reply-a",
        ),
        before, after,
    )
    assert result["blockers"] == []
    assert [x["cell"] for x in result["cell_update_candidates"]] == [
        "G2", "V2"
    ]


def test_retry_after_reply_text_written():
    before = source(
        replies=("Original reply",),
        ids="reply-a",
    )
    after = source(
        replies=("Original reply", "New reply"),
        ids="reply-a | reply-b",
    )
    result = run(
        pm(
            replies=("Original reply", "New reply"),
            ids="reply-a",
        ),
        before, after,
    )
    assert result["blockers"] == []
    assert [x["cell"] for x in result["cell_update_candidates"]] == [
        "V2"
    ]


def test_retry_after_comment_written():
    result = run(
        pm(comment="Revised"),
        source(),
        source(comment="Revised"),
    )
    assert result["blockers"] == []
    assert result["cell_update_candidates"] == []


def test_conflicting_manual_edit_blocks_export():
    result = run(
        pm(comment="Human edit"),
        source(),
        source(comment="PDF revision"),
    )
    assert result["blockers"]
    assert result["cell_update_candidates"] == []


def test_manual_category_not_in_writes():
    result = run(
        pm(category="Important category"),
        source(),
        source(comment="Revised"),
    )
    assert all(
        not x["cell"].startswith("I")
        for x in result["cell_update_candidates"]
    )


def test_new_root_is_blocked_until_insertion_connected():
    updated = source() + [{
        "Root Entry ID": "root-2",
        "Comment": "New ROOT",
        "Reply Entry IDs": "",
    }]
    result = run(pm(), source(), updated)
    assert result["blockers"]
    assert result["cell_update_candidates"] == []


def test_historical_reply_display_difference_allows_comment_change():
    """An old PM display difference must not block a new comment."""
    before = source(
        replies=("Original PDF reply",),
        ids="reply-a",
    )
    after = source(
        comment="Revised",
        replies=("Original PDF reply",),
        ids="reply-a",
    )
    result = run(
        pm(
            replies=("Original PDF reply  ",),
            ids="reply-a",
        ),
        before,
        after,
    )
    assert result["blockers"] == []
    assert [
        item["cell"]
        for item in result["cell_update_candidates"]
    ] == ["E2"]


def test_existing_reply_edit_is_not_silently_authorized():
    before = source(
        replies=("Original reply",),
        ids="reply-a",
    )
    after = source(
        replies=("Changed reply",),
        ids="reply-a",
    )
    result = run(
        pm(
            replies=("Original reply",),
            ids="reply-a",
        ),
        before,
        after,
    )
    assert result["blockers"]
    assert result["cell_update_candidates"] == []


def test_reply_id_conflict_remains_blocked():
    before = source(
        replies=("Original reply",),
        ids="reply-a",
    )
    after = source(
        comment="Revised",
        replies=("Original reply",),
        ids="reply-a",
    )
    result = run(
        pm(
            replies=("Original reply",),
            ids="different-reply-id",
        ),
        before,
        after,
    )
    assert result["blockers"]
    assert result["cell_update_candidates"] == []
