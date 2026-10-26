import copy
import pytest
from v2_pm_cell_plan import PM_HEADER_SEQUENCE
from v2_pm_dynamic_column_writer import DynamicReplyColumnWriter


class Call:
    def __init__(self, value): self.value = value
    def execute(self): return self.value


class FakeService:
    def __init__(self):
        self.headers = PM_HEADER_SEQUENCE + ['PM Custom']
        self.width = len(self.headers)
        self.writes = 0
        self.fail_header = False
    def spreadsheets(self): return self
    def values(self): return self
    def get(self, **kw):
        if 'fields' in kw:
            return Call({'sheets': [{'properties': {'title': 'Trial PDF - All Data',
                                                     'sheetId': 42,
                                                     'gridProperties': {'columnCount': self.width}}}]})
        return Call({'values': [self.headers.copy()]})
    def batchUpdate(self, **kw):
        req = kw['body']['requests'][0]['appendDimension']
        assert req['sheetId'] == 42
        self.width += req['length']
        self.headers += [''] * req['length']
        self.writes += 1
        return Call({})
    def update(self, **kw):
        if self.fail_header: raise RuntimeError('HEADER_WRITE_FAILED')
        additions = kw['body']['values'][0]
        self.headers[-len(additions):] = additions
        self.writes += 1
        return Call({})


def projection(depth):
    return [{**{f'Reply {i}': f'body{i}' for i in range(1, depth+1)},
             'Reply Entry IDs': ' | '.join(f'r{i}' for i in range(1, depth+1))}]


def writer(fake):
    return DynamicReplyColumnWriter(fake, 'staging', 'Trial PDF - All Data',
                                     authorized_spreadsheet_id='staging',
                                     authorized_tab='Trial PDF - All Data')


def test_dry_run_no_writes():
    f = FakeService()
    assert writer(f).apply(projection(4))['appended'] == ['Reply 4']
    assert f.writes == 0


def test_append_once_then_retry_without_writes():
    f = FakeService()
    assert writer(f).apply(projection(5), allow_writes=True)['appended'] == ['Reply 4', 'Reply 5']
    assert f.headers[-3:] == ['PM Custom', 'Reply 4', 'Reply 5']
    assert writer(f).apply(projection(5), allow_writes=True)['writes'] == 0
    assert f.writes == 2


def test_failed_header_write_stops_retry_without_duplicate():
    f = FakeService(); f.fail_header = True
    with pytest.raises(RuntimeError, match='HEADER_WRITE_FAILED'):
        writer(f).apply(projection(4), allow_writes=True)
    assert f.width == 24
    f.fail_header = False
    with pytest.raises(RuntimeError, match='PM_TRAILING_BLANK_COLUMN_REQUIRES_REVIEW'):
        writer(f).apply(projection(4), allow_writes=True)
    assert f.writes == 1



def test_destination_guard():
    with pytest.raises(PermissionError):
        DynamicReplyColumnWriter(FakeService(), 'production', 'Trial PDF - All Data',
                                 authorized_spreadsheet_id='staging',
                                 authorized_tab='Trial PDF - All Data')

class ReuseFake(FakeService):
    def __init__(self, extra_empty=1):
        super().__init__()
        self.headers = PM_HEADER_SEQUENCE + [''] * extra_empty
        self.width = len(self.headers)
        self.extra_data = []
    def get(self, **kw):
        if 'fields' in kw:
            return super().get(**kw)
        # Sheets trims empty trailing grid cells.
        values = [self.headers.copy()] + [list(row) for row in self.extra_data]
        return Call({'values': [list(row[:self.width]) for row in values]})
    def update(self, **kw):
        if self.fail_header:
            raise RuntimeError('HEADER_WRITE_FAILED')
        import re
        start = re.search(r'!([A-Z]+)1:', kw['range']).group(1)
        pos = 0
        for ch in start:
            pos = pos * 26 + ord(ch) - 64
        additions = kw['body']['values'][0]
        assert self.headers[pos - 1:pos - 1 + len(additions)] == [''] * len(additions)
        self.headers[pos - 1:pos - 1 + len(additions)] = additions
        self.writes += 1
        return Call({})


def test_reuse_existing_blank_w_only_one_header_write():
    f = ReuseFake(1)
    result = writer(f).apply(projection(4), allow_writes=True,
                             reuse_trailing_blank=True)
    assert result == {'verified': True, 'appended': [], 'reused': ['Reply 4'], 'writes': 1}
    assert f.width == 23 and f.headers[22] == 'Reply 4'
    assert writer(f).apply(projection(4), allow_writes=True,
                            reuse_trailing_blank=True)['writes'] == 0
    assert f.writes == 1


def test_reuse_w_then_append_reply_five():
    f = ReuseFake(1)
    result = writer(f).apply(projection(5), allow_writes=True,
                             reuse_trailing_blank=True)
    assert result['reused'] == ['Reply 4']
    assert result['appended'] == ['Reply 5']
    assert f.headers[-2:] == ['Reply 4', 'Reply 5']
    assert f.width == 24 and f.writes == 2
    assert writer(f).apply(projection(5), allow_writes=True,
                            reuse_trailing_blank=True)['writes'] == 0


def test_preexisting_data_in_w_blocks_reuse():
    f = ReuseFake(1)
    f.extra_data = [[''] * 22 + ['PM confidential']]
    with pytest.raises(ValueError, match='UNNAMED_COLUMN_WITH_DATA'):
        writer(f).apply(projection(4), allow_writes=True,
                        reuse_trailing_blank=True)
    assert f.writes == 0


def test_missing_opt_in_keeps_legacy_fail_closed():
    f = ReuseFake(1)
    with pytest.raises(RuntimeError, match='PM_TRAILING_BLANK_COLUMN_REQUIRES_REVIEW'):
        writer(f).apply(projection(4), allow_writes=True)
    assert f.writes == 0


def test_reuse_header_failure_does_not_create_duplicate():
    f = ReuseFake(1)
    f.fail_header = True
    with pytest.raises(RuntimeError, match='HEADER_WRITE_FAILED'):
        writer(f).apply(projection(4), allow_writes=True,
                        reuse_trailing_blank=True)
    assert f.width == 23 and f.writes == 0
    f.fail_header = False
    assert writer(f).apply(projection(4), allow_writes=True,
                            reuse_trailing_blank=True)['writes'] == 1


def test_pm_owned_data_survives_reuse():
    f = ReuseFake(1)
    f.extra_data = [['KEEP'] + [''] * 21]
    assert writer(f).apply(projection(4), allow_writes=True,
                            reuse_trailing_blank=True)['verified']
    assert f.extra_data[0][0] == 'KEEP'
