"""Strict PM header-to-position mapping, preserving PM-owned extra columns.

No I/O. Every automation write must be mapped against live headers.
"""
import re
from v2_pm_cell_plan import PM_HEADER_SEQUENCE

_CELL = re.compile(r'^([A-Z]+)([1-9][0-9]*)$')


def letters(index):
    result = ''
    while index:
        index, rest = divmod(index - 1, 26)
        result = chr(65 + rest) + result
    return result


class PMColumnMapping:
    def __init__(self, physical_headers):
        self.headers = list(physical_headers)
        self.positions = {}
        for i, header in enumerate(self.headers):
            self.positions.setdefault(header, []).append(i)
        self.canonical_positions = []
        counts = {}
        for header in PM_HEADER_SEQUENCE:
            ordinal = counts.get(header, 0)
            self.canonical_positions.append(self.positions[header][ordinal])
            counts[header] = ordinal + 1
        self.position = {name: indices[0] for name, indices in self.positions.items() if name}
        self.last_column = letters(len(self.headers))
        self.writable_positions = frozenset(self.position[name] for name in (
            'Comment', 'Reply 1', 'Reply 2', 'Reply 3', 'Reply Entry IDs'
        ))

    @classmethod
    def from_rows(cls, rows, grid_width):
        if grid_width < 22 or not rows:
            raise RuntimeError('PM_GRID_STRUCTURE_CONFLICT')
        headers = [(str(x).strip() if x is not None else '') for x in rows[0]]
        headers.extend([''] * (grid_width - len(headers)))
        if len(headers) != grid_width:
            raise RuntimeError('PM_GRID_STRUCTURE_CONFLICT')
        from collections import Counter
        actual = Counter(h for h in headers if h)
        expected = Counter(PM_HEADER_SEQUENCE)
        duplicates = [h for h,n in actual.items() if n > expected.get(h, 1)]
        if duplicates:
            raise RuntimeError('PM_DUPLICATE_HEADER: ' + repr(duplicates))
        absent = [h for h,n in expected.items() if actual[h] < n]
        if absent:
            raise RuntimeError('PM_MISSING_MANAGED_HEADER: ' + repr(sorted(absent)))
        for column, header in enumerate(headers):
            if not header and any(
                len(row)>column and str(row[column] if row[column] is not None else '').strip()
                for row in rows[1:]
            ):
                raise RuntimeError('PM_UNNAMED_COLUMN_WITH_DATA')
        return cls(headers)

    def check_headers(self, rows):
        if not rows:
            raise RuntimeError('PM_EMPTY_GRID')
        actual = [(str(x).strip() if x is not None else '') for x in rows[0]]
        actual.extend([''] * (len(self.headers) - len(actual)))
        if actual != self.headers:
            raise RuntimeError('PM_HEADERS_CHANGED_DURING_EXPORT')

    def canonical_rows(self, rows):
        self.check_headers(rows)
        indices = self.canonical_positions
        return [list(PM_HEADER_SEQUENCE)] + [
            [str(row[i]) if i < len(row) and row[i] is not None else '' for i in indices]
            for row in rows[1:]
        ]

    def physical_cell(self, cell):
        match = _CELL.fullmatch(cell)
        if not match:
            raise ValueError('INVALID_CANONICAL_CELL')
        n=0
        for char in match.group(1):
            n=n*26+ord(char)-64
        if not 1<=n<=22:
            raise RuntimeError('UNAUTHORIZED_CANONICAL_COLUMN')
        header=PM_HEADER_SEQUENCE[n-1]
        return f'{letters(self.canonical_positions[n-1]+1)}{match.group(2)}'

    def physical_row(self, canonical):
        if len(canonical)!=22:
            raise RuntimeError('PM_CANONICAL_ROW_WIDTH_CONFLICT')
        result=['']*len(self.headers)
        for n,index in enumerate(self.canonical_positions):
            result[index]=str(canonical[n]) if canonical[n] is not None else ''
        return result
