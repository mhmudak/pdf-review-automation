import pytest
from v2_pm_dynamic_reply_cells import plan_dynamic_reply_cells


def state(n):
    return {"Root Entry ID": "root", "Reply Entry IDs": " | ".join(f"id{i}" for i in range(1,n+1)), **{f"Reply {i}": f"text{i}" for i in range(1,n+1)}}


def sheet():
    return [["Custom", "Reply 4", "Reply Entry IDs", "Root Entry ID", "Reply 1", "Reply 2", "Reply 3"], ["keep", "", "id1 | id2 | id3", "root", "text1", "text2", "text3"]]


def test_reply4_after_custom_header_reorder():
    p=plan_dynamic_reply_cells(sheet(), [state(3)], [state(4)])
    assert p["blockers"] == []
    assert [(x["cell"],x["new_value"]) for x in p["cell_update_candidates"]] == [("B2", "text4"),("C2", "id1 | id2 | id3 | id4")]


def test_missing_reply_column_blocked():
    grid=sheet();grid[0][1]="Other"
    p=plan_dynamic_reply_cells(grid,[state(3)],[state(4)])
    assert p["blockers"][0][1]=="REPLY_COLUMN_NOT_CREATED"
    assert p["cell_update_candidates"]==[]


def test_existing_reply_modified_blocked():
    a=state(4);a["Reply 2"]="edited"
    p=plan_dynamic_reply_cells(sheet(),[state(3)],[a])
    assert p["blockers"][0][1]=="EXISTING_REPLY_CHANGED"


def test_pm_id_conflict_blocked():
    grid=sheet();grid[1][2]="other"
    p=plan_dynamic_reply_cells(grid,[state(3)],[state(4)])
    assert p["blockers"][0][1]=="PM_REPLY_ID_BASELINE_CONFLICT"


def test_duplicate_root_rejected():
    grid=sheet();grid.append(list(grid[1]))
    with pytest.raises(ValueError,match="PM_ROOT_ID_CONFLICT"):
        plan_dynamic_reply_cells(grid,[state(3)],[state(4)])


def test_idempotent_no_new_update():
    p=plan_dynamic_reply_cells(sheet(),[state(3)],[state(3)])
    assert p["cell_update_candidates"]==[]


def test_changed_order_rejected():
    a=state(4);a["Reply Entry IDs"]="id2 | id1 | id3 | id4"
    p=plan_dynamic_reply_cells(sheet(),[state(3)],[a])
    assert p["blockers"][0][1]=="REPLY_NON_SINGLE_APPEND"


def test_retry_when_reply_text_was_written_before_failure():
    grid=sheet();grid[1][1]='text4'
    p=plan_dynamic_reply_cells(grid,[state(3)],[state(4)])
    assert p['blockers']==[]
    assert [x['cell'] for x in p['cell_update_candidates']]==['C2']


def test_retry_when_reply_ids_were_written_before_failure():
    grid=sheet();grid[1][2]='id1 | id2 | id3 | id4'
    p=plan_dynamic_reply_cells(grid,[state(3)],[state(4)])
    assert p['blockers']==[]
    assert [x['cell'] for x in p['cell_update_candidates']]==['B2']


def test_retry_when_both_cells_already_written():
    grid=sheet();grid[1][1]='text4';grid[1][2]='id1 | id2 | id3 | id4'
    p=plan_dynamic_reply_cells(grid,[state(3)],[state(4)])
    assert p['blockers']==[]
    assert p['cell_update_candidates']==[]


def test_retry_rejects_unexpected_destination_reply():
    grid=sheet();grid[1][1]='manually changed'
    p=plan_dynamic_reply_cells(grid,[state(3)],[state(4)])
    assert p['blockers'][0][1]=='NEW_REPLY_TARGET_CONFLICT'


def test_same_ids_with_changed_existing_reply_is_blocked():
    changed=state(3);changed['Reply 2']='something else'
    p=plan_dynamic_reply_cells(sheet(),[state(3)],[changed])
    assert p['blockers'][0][1]=='EXISTING_REPLY_CHANGED'


def test_different_fourth_id_on_retry_is_blocked():
    grid=sheet();grid[1][2]='id1 | id2 | id3 | id444'
    p=plan_dynamic_reply_cells(grid,[state(3)],[state(4)])
    assert p['blockers'][0][1]=='PM_REPLY_ID_BASELINE_CONFLICT'


def test_approved_alias_does_not_block_new_reply():
    old = state(3)
    old["Reply 1"] = "S.A.I.D..F.A.R.H.A.T ? ok\n\n2026-10-05T21:53:49+03:00"
    current = dict(state(4))
    current["Reply 1"] = "Said Farhat ? ok\n\n2026-10-05T21:53:49+03:00"
    grid = sheet()
    grid[1][4] = "Said Farhat — ok\n\n05/10/2026 9:53:49 PM"
    result = plan_dynamic_reply_cells(grid, [old], [current], approved_author_aliases={"S.A.I.D..F.A.R.H.A.T": "Said Farhat"})
    assert result["blockers"] == []
    assert [x["field"] for x in result["cell_update_candidates"]] == ["Reply 4", "Reply Entry IDs"]


@pytest.mark.parametrize("mutation", [
    "Said Farhat ? edited\n\n2026-10-05T21:53:49+03:00",
    "Said Farhat ? ok\n\n2026-10-05T21:53:50+03:00",
])
def test_alias_cannot_hide_body_or_timestamp_change(mutation):
    old = state(3)
    old["Reply 1"] = "S.A.I.D..F.A.R.H.A.T ? ok\n\n2026-10-05T21:53:49+03:00"
    current = state(4)
    current["Reply 1"] = mutation
    result = plan_dynamic_reply_cells(sheet(), [old], [current], approved_author_aliases={"S.A.I.D..F.A.R.H.A.T": "Said Farhat"})
    assert result["blockers"][0][1] == "EXISTING_REPLY_CHANGED"


def test_unapproved_alias_stays_blocked():
    old = state(3)
    old["Reply 1"] = "Raw Name ? ok"
    current = state(4)
    current["Reply 1"] = "New Name ? ok"
    result = plan_dynamic_reply_cells(sheet(), [old], [current])
    assert result["blockers"][0][1] == "EXISTING_REPLY_CHANGED"
