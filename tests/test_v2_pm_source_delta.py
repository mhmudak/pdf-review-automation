import pytest

from v2_pm_source_delta import plan_verified_source_delta


def r(key, **fields):
    return {"Root Entry ID": key, **fields}


def test_unchanged_source_creates_no_changes():
    row = r("a", Comment="Same")
    plan = plan_verified_source_delta([row], [row], [row])
    assert plan["verified_cell_update_candidates"] == []
    assert plan["held_for_review"] == []


def test_verified_comment_edit_is_candidate():
    plan = plan_verified_source_delta(
        [r("a", Comment="Old", Category="Manual")],
        [r("a", Comment="Old")],
        [r("a", Comment="New")],
    )
    updates = plan["verified_cell_update_candidates"]
    assert len(updates) == 1
    assert updates[0]["field"] == "Comment"
    assert updates[0]["new_value"] == "New"
    assert plan["google_write_operations"] == []


def test_manual_pm_edit_blocks_overwrite():
    plan = plan_verified_source_delta(
        [r("a", Comment="PM manually edited")],
        [r("a", Comment="Old")],
        [r("a", Comment="New")],
    )
    assert plan["verified_cell_update_candidates"] == []
    assert plan["held_for_review"][0]["reason"] == (
        "PM_SOURCE_CONFLICT"
    )


def test_new_root_is_append_candidate_only():
    plan = plan_verified_source_delta(
        [r("a", Comment="Old")],
        [r("a", Comment="Old")],
        [r("a", Comment="Old"), r("b", Comment="New")],
    )
    assert len(plan["new_root_candidates"]) == 1
    assert plan["google_write_operations"] == []


def test_existing_pm_id_blocks_duplicate_append():
    plan = plan_verified_source_delta(
        [r("a"), r("b", Comment="Historical")],
        [r("a")],
        [r("a"), r("b", Comment="New")],
    )
    assert plan["new_root_candidates"] == []
    assert plan["held_for_review"][0]["reason"] == (
        "NEW_SOURCE_ID_ALREADY_IN_PM"
    )


def test_removed_root_is_preserved():
    plan = plan_verified_source_delta(
        [r("a"), r("b")],
        [r("a"), r("b")],
        [r("a")],
    )
    assert plan["historical_root_ids"] == ["b"]
    assert plan["deletion_operations"] == []


def test_reply_change_is_held():
    plan = plan_verified_source_delta(
        [r("a", **{"Reply 1": "Old"})],
        [r("a", **{"Reply 1": "Old"})],
        [r("a", **{"Reply 1": "New"})],
    )
    assert plan["verified_cell_update_candidates"] == []
    assert plan["held_for_review"][0]["reason"] == (
        "REPLY_CHANGE_NEEDS_ID_AWARE_PLANNER"
    )


def test_baseline_missing_from_pm_rejected():
    with pytest.raises(ValueError):
        plan_verified_source_delta(
            [r("a")],
            [r("a"), r("b")],
            [r("a"), r("b")],
        )


@pytest.mark.parametrize("which", ["pm", "before", "after"])
def test_duplicate_ids_rejected(which):
    pm = [r("a")]
    before = [r("a")]
    after = [r("a")]

    datasets = {"pm": pm, "before": before, "after": after}
    datasets[which].append(r("a"))

    with pytest.raises(ValueError):
        plan_verified_source_delta(pm, before, after)
