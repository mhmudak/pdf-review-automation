"""Pure planner: dynamic replies are physically adjacent, never appended at far right."""
import pytest
from v2_pm_cell_plan import PM_HEADER_SEQUENCE
from v2_pm_dynamic_reply_columns import plan_reply_column_expansion


def projection(depth):
    row = {f'Reply {i}': f'Body {i}' for i in range(1, depth + 1)}
    row['Reply Entry IDs'] = ' | '.join(f'id-{i}' for i in range(1, depth + 1))
    return [row]


def test_fourth_reply_inserts_before_category_and_keeps_custom():
    headers = PM_HEADER_SEQUENCE + ['Custom PM', '']
    result = plan_reply_column_expansion([headers], 24, projection(4))
    assert result['append_headers'] == ['Reply 4']
    at = PM_HEADER_SEQUENCE.index('Category')
    assert result['insert_index'] == at
    assert result['expected_headers'][at:at+2] == ['Reply 4','Category']
    assert result['expected_headers'][-2:] == ['Custom PM','']


def test_fifth_reply_inserts_immediately_after_four_and_retry_is_idempotent():
    at = PM_HEADER_SEQUENCE.index('Category')
    headers = PM_HEADER_SEQUENCE[:at]+['Reply 4']+PM_HEADER_SEQUENCE[at:]+['Custom']
    result = plan_reply_column_expansion([headers], 24, projection(5))
    assert result['insert_index'] == at+1
    assert result['append_headers'] == ['Reply 5']
    again = plan_reply_column_expansion([result['expected_headers']], 25, projection(5))
    assert again['append_headers'] == []


def test_existing_three_requires_no_columns():
    assert plan_reply_column_expansion([PM_HEADER_SEQUENCE],22,projection(3))['append_headers']==[]


def test_fails_if_unnamed_column_has_values():
    with pytest.raises(ValueError, match='UNNAMED_COLUMN_WITH_DATA'):
        plan_reply_column_expansion([PM_HEADER_SEQUENCE + [''], [''] * 22 + ['PRIVATE']],23,projection(4))


def test_fails_on_duplicate_reply_header():
    with pytest.raises(ValueError, match='PM_DUPLICATE_HEADER'):
        plan_reply_column_expansion([PM_HEADER_SEQUENCE + ['Reply 3']],23,projection(4))


def test_fails_on_gapped_reply_headers():
    with pytest.raises(ValueError, match='NON_CONTIGUOUS_REPLY_HEADERS'):
        plan_reply_column_expansion([PM_HEADER_SEQUENCE + ['Reply 5']],23,projection(5))


def test_fails_on_text_id_mismatch():
    bad=projection(4);bad[0]['Reply Entry IDs']='id-1'
    with pytest.raises(ValueError,match='REPLY_TEXT_ID_COUNT_MISMATCH'):
        plan_reply_column_expansion([PM_HEADER_SEQUENCE],22,bad)


def test_fails_on_gap_in_projection():
    bad=projection(5);bad[0]['Reply 4']=''
    with pytest.raises(ValueError,match='NON_CONTIGUOUS_REPLY_VALUES'):
        plan_reply_column_expansion([PM_HEADER_SEQUENCE],22,bad)


def test_nonadjacent_existing_replies_fail_closed():
    headers=PM_HEADER_SEQUENCE[:7]+['Custom']+PM_HEADER_SEQUENCE[7:]
    with pytest.raises(ValueError, match='PM_REPLY_COLUMNS_NOT_ADJACENT'):
        plan_reply_column_expansion([headers],23,projection(4))


def test_blank_after_reply_three_recovery_requires_authorization():
    at=PM_HEADER_SEQUENCE.index('Category')
    headers=PM_HEADER_SEQUENCE[:at]+['']+PM_HEADER_SEQUENCE[at:]
    with pytest.raises(RuntimeError,match='PM_BLANK_REPLY_SLOT_REQUIRES_REVIEW'):
        plan_reply_column_expansion([headers],23,projection(4))
    result=plan_reply_column_expansion([headers],23,projection(4),reuse_trailing_blank=True)
    assert result['reuse_headers']==['Reply 4']
    assert result['append_headers']==[]
