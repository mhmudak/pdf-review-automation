import pytest

from v2_pm_cell_plan import PM_HEADER_SEQUENCE
from v2_pm_export_coordinator import verify_unchanged_pm


ROOT = "root-a"


def source():
    return [{
        "Root Entry ID": ROOT,
        "Comment": "Verified PDF comment",
        "Reply Entry IDs": "reply-1 | reply-2",
        "Reply 1": "Source reply one",
        "Reply 2": "Source reply two",
    }]


def pm():
    row = [""] * 22
    row[4] = "Verified PDF comment"
    row[5] = "Historical displayed reply one"
    row[6] = "Historical displayed reply two"
    row[8] = "Human assigned category"
    row[14] = ROOT
    row[21] = "reply-1 | reply-2"
    return [list(PM_HEADER_SEQUENCE), row]


def test_full_destination_verification_passes():
    assert verify_unchanged_pm(pm(), source()) == 1


def test_historical_reply_display_is_preserved():
    values = pm()
    values[1][5] = "Human display formatting"
    assert verify_unchanged_pm(values, source()) == 1


def test_manual_category_is_not_overwritten():
    values = pm()
    values[1][8] = "Manually classified"
    assert verify_unchanged_pm(values, source()) == 1


def test_comment_conflict_blocks_completion():
    values = pm()
    values[1][4] = "Human revised comment"
    with pytest.raises(RuntimeError, match="PM_COMMENT_CONFLICT"):
        verify_unchanged_pm(values, source())


def test_reply_identity_conflict_blocks_completion():
    values = pm()
    values[1][21] = "reply-1 | unexpected-id"
    with pytest.raises(RuntimeError, match="PM_REPLY_ID_CONFLICT"):
        verify_unchanged_pm(values, source())


def test_missing_root_blocks_completion():
    values = pm()
    values[1][14] = "different-root"
    with pytest.raises(RuntimeError, match="PM_ROOT_SET_CONFLICT"):
        verify_unchanged_pm(values, source())


def test_duplicate_root_blocks_completion():
    values = pm()
    values.append(list(values[1]))
    with pytest.raises(RuntimeError, match="PM_ROOT_ID_CONFLICT"):
        verify_unchanged_pm(values, source())
