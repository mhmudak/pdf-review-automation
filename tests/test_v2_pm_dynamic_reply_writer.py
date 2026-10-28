"""No network: structural and guarded-writer integration tests."""
import pytest
from unittest.mock import patch
from v2_pm_dynamic_reply_writer import apply_dynamic_reply_plan

HEADERS = [
    'index', 'Book Page', 'PDF Page', 'Author', 'PDF Date (Last Modified)',
    'Selected Text', 'Comment', 'Reply 1', 'Reply 2', 'Reply 3', 'Category',
    'Annotation Type', 'PDF Link', 'PDF Page', 'Last Modified',
    'Root Entry ID', 'Entry Key', 'Version ID', 'Drive File ID', 'PDF SHA256',
    'Original Created Date', 'Original Modified Date', 'Reply Entry IDs',
    'Custom', 'Reply 4',
]
# The mandatory canonical schema from the repo is authoritative.
from v2_pm_cell_plan import PM_HEADER_SEQUENCE


def sample():
    headers = list(PM_HEADER_SEQUENCE) + ['Custom', 'Reply 4']
    row = [''] * len(headers)
    def put(field, value):
        row[headers.index(field)] = value
    put('Root Entry ID', 'root')
    put('Reply Entry IDs', 'id1 | id2 | id3')
    put('Reply 1', 'one')
    put('Reply 2', 'two')
    put('Reply 3', 'three')
    put('Custom', 'PM-owned')
    old = {'Root Entry ID': 'root', 'Reply Entry IDs': 'id1 | id2 | id3',
           'Reply 1': 'one', 'Reply 2': 'two', 'Reply 3': 'three'}
    new = {**old, 'Reply Entry IDs': 'id1 | id2 | id3 | id4',
           'Reply 4': 'four'}
    return [headers, row], old, new


def invoke(grid, before, after, **kwargs):
    return apply_dynamic_reply_plan(
        object(), 'stage', 'PM', authorized_spreadsheet_id='stage',
        authorized_tab='PM', sheet_values=grid, grid_width=len(grid[0]),
        previous_projection=[before], current_projection=[after], **kwargs,
    )


def test_guarded_writer_receives_physical_reply_cells():
    grid, before, after = sample()
    with patch('v2_pm_dynamic_reply_writer.GuardedPMWriter') as writer:
        writer.return_value.apply.return_value = {'verified': False, 'pending': ['X2','V2']}
        result = invoke(grid, before, after)
    assert result['planned_cells'] == ['X2', 'V2']
    mapping = writer.call_args.kwargs['column_mapping']
    assert mapping.writable_positions == frozenset({5,6,7,21,23})
    assert mapping.physical_cell('O2') == 'O2'
    changes = writer.return_value.apply.call_args.args[0]
    assert [(x.cell, x.new_value) for x in changes] == [('X2','four'), ('V2','id1 | id2 | id3 | id4')]


def test_reordered_pm_columns_keep_identity_lookup_correct():
    grid, before, after = sample()
    for row in grid:
        row[14], row[22] = row[22], row[14]
    with patch('v2_pm_dynamic_reply_writer.GuardedPMWriter') as writer:
        writer.return_value.apply.return_value = {'verified': False}
        invoke(grid, before, after)
    mapping = writer.call_args.kwargs['column_mapping']
    assert mapping.physical_cell('O2') == 'W2'


def test_destination_is_fail_closed():
    grid, before, after = sample()
    with pytest.raises(PermissionError, match='DYNAMIC_REPLY_DESTINATION'):
        apply_dynamic_reply_plan(object(), 'production', 'PM',
            authorized_spreadsheet_id='stage', authorized_tab='PM',
            sheet_values=grid, grid_width=len(grid[0]),
            previous_projection=[before], current_projection=[after])


def test_plan_blocker_prevents_writer_call():
    grid, before, after = sample()
    after['Reply 2'] = 'unexpected edit'
    with patch('v2_pm_dynamic_reply_writer.GuardedPMWriter') as writer:
        with pytest.raises(RuntimeError, match='DYNAMIC_REPLY_PLAN_REQUIRES_REVIEW'):
            invoke(grid, before, after)
    writer.assert_not_called()


def test_existing_custom_column_never_writable():
    grid, before, after = sample()
    with patch('v2_pm_dynamic_reply_writer.GuardedPMWriter') as writer:
        writer.return_value.apply.return_value = {'verified': False}
        invoke(grid, before, after)
    mapping = writer.call_args.kwargs['column_mapping']
    assert grid[0].index('Custom') not in mapping.writable_positions


def test_unexpected_duplicate_custom_header_rejected():
    grid, before, after = sample()
    grid[0][-1] = 'Custom'
    with pytest.raises(RuntimeError, match='PM_DUPLICATE_HEADER'):
        invoke(grid, before, after)


def test_missing_reply4_column_requires_review():
    grid, before, after = sample()
    grid[0][-1] = 'Extra PM'
    with patch('v2_pm_dynamic_reply_writer.GuardedPMWriter') as writer:
        with pytest.raises(RuntimeError, match='DYNAMIC_REPLY_PLAN_REQUIRES_REVIEW'):
            invoke(grid, before, after)
    writer.assert_not_called()
