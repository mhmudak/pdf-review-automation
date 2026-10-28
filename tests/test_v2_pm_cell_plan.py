import pytest

from v2_pm_cell_plan import (
    PM_HEADER_SEQUENCE,
    plan_pm_comment_cells,
)


def sheet(*rows):
    output = [list(PM_HEADER_SEQUENCE)]
    for root_id, comment in rows:
        row = [""] * 22
        row[14] = root_id
        row[4] = comment
        output.append(row)
    return output


def change(root_id, old, new):
    return {
        "root_entry_id": root_id,
        "field": "Comment",
        "expected_pm_value": old,
        "new_value": new,
        "reason": "VERIFIED_SOURCE_COMMENT_CHANGE",
    }


def test_empty_candidate_set_is_safe():
    result = plan_pm_comment_cells(
        sheet(("r1", "Text")), []
    )
    assert result["cell_update_candidates"] == []
    assert result["google_write_operations"] == []


def test_verified_comment_plans_exact_cell():
    result = plan_pm_comment_cells(
        sheet(("r1", "Old")),
        [change("r1", "Old", "New")],
    )
    assert result["cell_update_candidates"][0]["cell"] == "E2"
    assert result["cell_update_candidates"][0]["new_value"] == "New"


def test_correct_row_found_by_id_not_position():
    result = plan_pm_comment_cells(
        sheet(("r2", "B"), ("r1", "Old")),
        [change("r1", "Old", "New")],
    )
    assert result["cell_update_candidates"][0]["cell"] == "E3"


def test_retry_recognizes_already_applied_change():
    result = plan_pm_comment_cells(
        sheet(("r1", "New")),
        [change("r1", "Old", "New")],
    )
    assert result["cell_update_candidates"] == []
    assert result["already_applied_ids"] == ["r1"]


def test_manual_edit_blocks_overwrite():
    result = plan_pm_comment_cells(
        sheet(("r1", "PM edited")),
        [change("r1", "Old", "New")],
    )
    assert result["conflicts"][0]["reason"] == (
        "PM_VALUE_CHANGED"
    )
    assert result["cell_update_candidates"] == []


def test_missing_root_is_conflict():
    result = plan_pm_comment_cells(
        sheet(("r1", "Text")),
        [change("missing", "Old", "New")],
    )
    assert result["conflicts"][0]["reason"] == "ROOT_NOT_FOUND"


def test_duplicate_root_ids_rejected():
    with pytest.raises(ValueError):
        plan_pm_comment_cells(
            sheet(("r1", "A"), ("r1", "B")), []
        )


def test_duplicate_candidates_rejected():
    with pytest.raises(ValueError):
        plan_pm_comment_cells(
            sheet(("r1", "Old")),
            [
                change("r1", "Old", "New"),
                change("r1", "Old", "New"),
            ],
        )


def test_wrong_schema_is_rejected():
    values = sheet(("r1", "Old"))
    values[0][14] = "Incorrect ID Header"
    with pytest.raises(ValueError):
        plan_pm_comment_cells(values, [])


def test_unverified_change_is_rejected():
    candidate = change("r1", "Old", "New")
    candidate["reason"] = "UNKNOWN"
    with pytest.raises(ValueError):
        plan_pm_comment_cells(
            sheet(("r1", "Old")), [candidate]
        )


def test_input_remains_unchanged():
    values = sheet(("r1", "Old"))
    plan_pm_comment_cells(
        values, [change("r1", "Old", "New")]
    )
    assert values[1][4] == "Old"
    assert values[1][8] == ""
