import pytest

from v2_pm_cell_plan import PM_HEADER_SEQUENCE
from v2_pm_reply_cell_plan import plan_pm_reply_cells


def sheet(root="r1", ids="", replies=()):
    row = [""] * 22
    row[14] = root
    row[21] = ids
    for i, value in enumerate(replies):
        row[5 + i] = value
    return [list(PM_HEADER_SEQUENCE), row]


def previous(ids="", replies=()):
    row = {"Root Entry ID": "r1", "Reply Entry IDs": ids}
    for i, value in enumerate(replies, 1):
        row[f"Reply {i}"] = value
    return [row]


def candidate(number=1, rid="a", value="Reply text"):
    return [{
        "root_entry_id": "r1",
        "reply_entry_id": rid,
        "field": f"Reply {number}",
        "expected_pm_value": "",
        "new_value": value,
        "reason": "VERIFIED_NEW_REPLY_ID",
    }]


def test_first_reply_plans_two_cells():
    result = plan_pm_reply_cells(
        sheet(), previous(), candidate()
    )
    assert [r["cell"] for r in result["cell_update_candidates"]] == [
        "F2", "V2"
    ]


def test_second_reply_preserves_first():
    result = plan_pm_reply_cells(
        sheet(ids="a", replies=("Legacy display",)),
        previous(ids="a", replies=("Canonical display",)),
        candidate(2, "b", "Second reply"),
    )
    assert [r["cell"] for r in result["cell_update_candidates"]] == [
        "G2", "V2"
    ]
    assert result["cell_update_candidates"][1]["new_value"] == (
        "a | b"
    )


def test_fully_applied_retry_is_noop():
    result = plan_pm_reply_cells(
        sheet(ids="a", replies=("Reply text",)),
        previous(),
        candidate(),
    )
    assert result["cell_update_candidates"] == []
    assert len(result["already_applied"]) == 2


def test_partial_retry_with_ids_only():
    result = plan_pm_reply_cells(
        sheet(ids="a"),
        previous(),
        candidate(),
    )
    assert [r["cell"] for r in result["cell_update_candidates"]] == [
        "F2"
    ]


def test_partial_retry_with_text_only():
    result = plan_pm_reply_cells(
        sheet(replies=("Reply text",)),
        previous(),
        candidate(),
    )
    assert [r["cell"] for r in result["cell_update_candidates"]] == [
        "V2"
    ]


def test_existing_id_conflict_blocks_both_cells():
    result = plan_pm_reply_cells(
        sheet(ids="different"),
        previous(),
        candidate(),
    )
    assert result["cell_update_candidates"] == []
    assert result["conflicts"][0][1] == "REPLY_ID_CONFLICT"


def test_existing_text_conflict_blocks_both_cells():
    result = plan_pm_reply_cells(
        sheet(replies=("Manual text",)),
        previous(),
        candidate(),
    )
    assert result["cell_update_candidates"] == []
    assert result["conflicts"][0][1] == "REPLY_TEXT_CONFLICT"


def test_fourth_reply_requires_schema_extension():
    result = plan_pm_reply_cells(
        sheet(ids="a | b | c", replies=("A", "B", "C")),
        previous(ids="a, b, c", replies=("A", "B", "C")),
        candidate(4, "d", "Fourth reply"),
    )
    assert result["cell_update_candidates"] == []
    assert result["conflicts"][0][1] == (
        "DYNAMIC_REPLY_COLUMN_REQUIRED"
    )


def test_duplicate_root_candidates_rejected():
    with pytest.raises(ValueError):
        plan_pm_reply_cells(
            sheet(), previous(), candidate() + candidate()
        )


def test_unverified_candidate_rejected():
    values = candidate()
    values[0]["reason"] = "UNKNOWN"
    with pytest.raises(ValueError):
        plan_pm_reply_cells(sheet(), previous(), values)


def test_input_is_not_mutated():
    values = sheet()
    plan_pm_reply_cells(values, previous(), candidate())
    assert values[1][5] == ""
    assert values[1][21] == ""
