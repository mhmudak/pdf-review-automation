"""Insert Reply N next to Reply N-1 without disturbing PM-owned columns."""
import re
import pytest
from v2_pm_cell_plan import PM_HEADER_SEQUENCE
from v2_pm_dynamic_column_writer import DynamicReplyColumnWriter


class Call:
    def __init__(self, value): self.value = value
    def execute(self): return self.value


class FakeService:
    def __init__(self, trailing_blank=True):
        self.headers = list(PM_HEADER_SEQUENCE) + ([''] if trailing_blank else [])
        self.rows = [['KEEP'] + [''] * 4 + ['original'] + [''] * (len(self.headers)-6)]
        self.width = len(self.headers)
        self.writes = 0
        self.fail_header = False
    def spreadsheets(self): return self
    def values(self): return self
    def get(self, **kw):
        if 'fields' in kw:
            return Call({'sheets': [{'properties': {'title': 'Trial PDF - All Data',
                'sheetId': 42, 'gridProperties': {'columnCount': self.width}}}]})
        return Call({'values': [self.headers[:]] + [r[:] for r in self.rows]})
    def batchUpdate(self, **kw):
        req = kw['body']['requests'][0]['insertDimension']
        loc = req['range']
        assert loc['sheetId'] == 42 and loc['dimension'] == 'COLUMNS'
        start, end = loc['startIndex'], loc['endIndex']
        self.headers[start:start] = [''] * (end-start)
        for row in self.rows:
            row[start:start] = [''] * (end-start)
        self.width += end-start
        self.writes += 1
        return Call({})
    def update(self, **kw):
        if self.fail_header: raise RuntimeError('HEADER_WRITE_FAILED')
        match = re.search(r'!([A-Z]+)1:', kw['range'])
        first = 0
        for char in match.group(1): first = first * 26 + ord(char) - 64
        start = first - 1
        values = kw['body']['values'][0]
        assert self.headers[start:start+len(values)] == [''] * len(values)
        self.headers[start:start+len(values)] = values
        self.writes += 1
        return Call({})


def projection(depth):
    return [{**{f'Reply {i}': f'body{i}' for i in range(1, depth+1)},
             'Reply Entry IDs': ' | '.join(f'r{i}' for i in range(1, depth+1))}]


def writer(fake):
    return DynamicReplyColumnWriter(fake, 'staging', 'Trial PDF - All Data',
                                     authorized_spreadsheet_id='staging',
                                     authorized_tab='Trial PDF - All Data')


def assert_adjacent(headers, depth):
    at = headers.index('Reply 1')
    assert headers[at:at+depth] == [f'Reply {i}' for i in range(1, depth+1)]
    assert headers[at+depth] == 'Category'


def test_dry_run_no_writes():
    f = FakeService()
    assert writer(f).apply(projection(4))['appended'] == ['Reply 4']
    assert f.writes == 0


def test_four_then_five_and_idempotent_with_trailing_blank():
    f = FakeService()
    original = f.rows[0][:]
    assert writer(f).apply(projection(4), allow_writes=True)['verified']
    assert_adjacent(f.headers, 4)
    assert f.headers[-1] == ''
    assert writer(f).apply(projection(5), allow_writes=True)['verified']
    assert_adjacent(f.headers, 5)
    assert f.headers[-1] == ''
    assert f.rows[0] == original[:8] + ['', ''] + original[8:]
    assert writer(f).apply(projection(5), allow_writes=True)['writes'] == 0
    assert f.writes == 4


def test_header_failure_then_gated_recovery_reuses_blank_slot():
    f = FakeService(); f.fail_header = True
    with pytest.raises(RuntimeError, match='HEADER_WRITE_FAILED'):
        writer(f).apply(projection(4), allow_writes=True)
    assert f.width == 24
    f.fail_header = False
    with pytest.raises(RuntimeError, match='PM_BLANK_REPLY_SLOT_REQUIRES_REVIEW'):
        writer(f).apply(projection(4), allow_writes=True)
    result = writer(f).apply(projection(4), allow_writes=True,
                             reuse_trailing_blank=True)
    assert result['reused'] == ['Reply 4']
    assert_adjacent(f.headers, 4)
    assert f.width == 24


def test_existing_custom_data_and_unnamed_blank_shift_safely():
    f = FakeService()
    f.headers[-1] = 'PM Custom'
    f.rows[0][-1] = 'do not overwrite'
    before = f.rows[0][:]
    writer(f).apply(projection(4), allow_writes=True)
    assert f.rows[0] == before[:8] + [''] + before[8:]
    assert f.headers[-1] == 'PM Custom'
    assert_adjacent(f.headers, 4)


def test_destination_guard():
    with pytest.raises(PermissionError):
        DynamicReplyColumnWriter(FakeService(), 'production', 'Trial PDF - All Data',
                                 authorized_spreadsheet_id='staging',
                                 authorized_tab='Trial PDF - All Data')


def test_data_in_unlabelled_column_is_rejected():
    f = FakeService()
    f.rows[0][-1] = 'secret'
    with pytest.raises(ValueError, match='UNNAMED_COLUMN_WITH_DATA'):
        writer(f).apply(projection(4), allow_writes=True)
    assert f.writes == 0
