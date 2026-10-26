"""Staging-only, fail-closed PM reply header append operation.

No source/reply content writes. Call only after a verified expansion plan.
An interrupted Sheets append must be reconciled before retry; this helper
never silently consumes existing blank/custom columns.
"""
from __future__ import annotations

from v2_pm_dynamic_reply_columns import plan_reply_column_expansion


class DynamicReplyColumnWriter:
    def __init__(self, service, spreadsheet_id, tab, *, authorized_spreadsheet_id,
                 authorized_tab):
        if spreadsheet_id != authorized_spreadsheet_id or tab != authorized_tab:
            raise PermissionError('PM_COLUMN_DESTINATION_NOT_AUTHORIZED')
        self.service = service
        self.spreadsheet_id = spreadsheet_id
        self.tab = tab

    def _grid_width(self):
        data = self.service.spreadsheets().get(
            spreadsheetId=self.spreadsheet_id,
            fields='sheets(properties(title,gridProperties(columnCount)))',
        ).execute()
        found = [s['properties']['gridProperties']['columnCount']
                 for s in data['sheets'] if s['properties']['title'] == self.tab]
        if len(found) != 1:
            raise RuntimeError('PM_GRID_STRUCTURE_CONFLICT')
        return int(found[0])

    @staticmethod
    def _letter(zero_based):
        result = ''
        n = zero_based + 1
        while n:
            n, r = divmod(n - 1, 26)
            result = chr(65 + r) + result
        return result

    def _rows(self, width):
        return self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"'{self.tab}'!A1:{self._letter(width - 1)}",
            valueRenderOption='FORMATTED_VALUE',
        ).execute().get('values', [])

    def apply(self, projection, *, allow_writes=False, reuse_trailing_blank=False):
        """Append missing headers; never write reply cells or source values.

        Rereads the live grid and planner; racing header changes fail closed
        on readback, and an interrupted blank-column append is not silently
        considered successful.
        """
        before_width = self._grid_width()
        before_rows = self._rows(before_width)
        plan = plan_reply_column_expansion(
            before_rows, before_width, projection,
            reuse_trailing_blank=reuse_trailing_blank,
        )
        additions = plan['append_headers']
        reused = plan['reuse_headers']
        if not additions and not reused:
            return {'verified': True, 'appended': [], 'reused': [], 'writes': 0}
        if not allow_writes:
            return {'verified': False, 'appended': additions, 'reused': reused, 'writes': 0}

        # Re-read just before the first structural API request.
        if self._grid_width() != before_width or self._rows(before_width) != before_rows:
            raise RuntimeError('PM_COLUMNS_CHANGED_BEFORE_WRITE')
        api = self.service.spreadsheets()
        if additions:
            at = plan['insert_index']
            api.batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={'requests': [{'insertDimension': {
                    'range': {'sheetId': self._sheet_id(), 'dimension': 'COLUMNS',
                              'startIndex': at, 'endIndex': at + len(additions)},
                    'inheritFromBefore': True,
                }}]},
            ).execute()
        # A crash after insertDimension leaves blank slots after Reply N;
        # verified recovery reuses those slots without inserting again.
        start = plan['new_header_indices'][0]
        headers_to_write = reused + additions
        api.values().update(
            spreadsheetId=self.spreadsheet_id,
            range=(f"'{self.tab}'!{self._letter(start)}1:"
                   f"{self._letter(start + len(headers_to_write) - 1)}1"),
            valueInputOption='RAW',
            body={'values': [headers_to_write]},
        ).execute()
        after_width = self._grid_width()
        after_rows = self._rows(after_width)
        if after_width != before_width + len(additions):
            raise RuntimeError('PM_COLUMN_INSERT_READBACK_FAILED')
        expected = plan['expected_headers']
        actual_headers = list(after_rows[0]) + [''] * (after_width - len(after_rows[0]))
        if actual_headers != expected:
            raise RuntimeError('PM_HEADER_INSERT_READBACK_FAILED')
        # Verify every existing data cell, including PM-owned custom cells.
        # Only header cells can have changed in this operation.
        # Inserted columns shift all existing cells; a reused blank slot does not.
        inserted_at = plan['insert_index']
        def shifted(row):
            full = list(row) + [''] * (before_width - len(row))
            return (full[:inserted_at] + [''] * len(additions)
                    + full[inserted_at:])
        if ([list(r) + [''] * (after_width - len(r)) for r in after_rows[1:]]
                != [shifted(r) for r in before_rows[1:]]):
            raise RuntimeError('PM_EXISTING_DATA_CHANGED')
        if plan_reply_column_expansion(after_rows, after_width, projection,
                                       reuse_trailing_blank=reuse_trailing_blank)['append_headers']:
            raise RuntimeError('PM_COLUMN_EXPANSION_UNVERIFIED')
        return {'verified': True, 'appended': additions, 'reused': reused,
                'writes': (1 if additions else 0) + 1}

    def _sheet_id(self):
        result = self.service.spreadsheets().get(
            spreadsheetId=self.spreadsheet_id,
            fields='sheets(properties(sheetId,title))',
        ).execute()
        matches = [item['properties']['sheetId'] for item in result['sheets']
                   if item['properties']['title'] == self.tab]
        if len(matches) != 1:
            raise RuntimeError('PM_TAB_NOT_FOUND')
        return matches[0]
