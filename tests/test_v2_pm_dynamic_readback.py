import pytest
from v2_pm_dynamic_readback import verify_dynamic_reply_readback


def records(old=False):
    result = {"Root Entry ID":"root-a","Reply Entry IDs":"i1 | i2 | i3","Reply 1":"Old author — first","Reply 2":"second","Reply 3":"third"}
    if not old:
        result.update({"Reply Entry IDs":"i1 | i2 | i3 | i4","Reply 4":"fourth"})
    return result


def grid(reply4="fourth", ids="i1 | i2 | i3 | i4"):
    return [["Category","Reply 4","Reply Entry IDs","Root Entry ID","Reply 1","Reply 2","Reply 3","Custom"],
            ["MANUAL",reply4,ids,"root-a","Historical alternate display","second","third","owner value"]]


def test_fourth_reply_verified_in_reordered_grid():
    result=verify_dynamic_reply_readback(grid(),[records()],previous_projection=[records(old=True)])
    assert result["new_reply_cells"] == 1


def test_missing_fourth_reply_rejected():
    with pytest.raises(RuntimeError,match="PM_NEW_REPLY_TEXT_CONFLICT"):
        verify_dynamic_reply_readback(grid(reply4=""),[records()],previous_projection=[records(old=True)])


def test_changed_reply_id_rejected():
    with pytest.raises(RuntimeError,match="PM_REPLY_ID_CONFLICT"):
        verify_dynamic_reply_readback(grid(ids="i1 | i2 | x | i4"),[records()],previous_projection=[records(old=True)])


def test_missing_reply_column_rejected():
    rows=grid();rows[0][1]="Other"
    with pytest.raises(RuntimeError,match="PM_REPLY_COLUMN_MISSING"):
        verify_dynamic_reply_readback(rows,[records()],previous_projection=[records(old=True)])


def test_missing_root_rejected():
    with pytest.raises(RuntimeError,match="PM_ROOT_SET_CONFLICT"):
        verify_dynamic_reply_readback([grid()[0]],[records()],previous_projection=[records(old=True)])


def test_bad_reply_prefix_in_source_rejected():
    current=records();current["Reply Entry IDs"]="x | i2 | i3 | i4"
    with pytest.raises(RuntimeError,match="SOURCE_REPLY_ID_REORDER"):
        verify_dynamic_reply_readback(grid(ids=current["Reply Entry IDs"]),[current],previous_projection=[records(old=True)])


def test_repeated_verification_is_read_only():
    rows=grid();before=repr(rows)
    for _ in range(2):
        assert verify_dynamic_reply_readback(rows,[records()],previous_projection=[records(old=True)])["verified"]
    assert repr(rows)==before
