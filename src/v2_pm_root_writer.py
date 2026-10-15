"""Protected, idempotent PM ROOT insertion for PrOps V2.

Never rewrites or sorts existing rows.
Input must be a fully prepared 22-column PM row.
Writes are explicitly authorized and disabled by default.
"""

from __future__ import annotations

from v2_pm_cell_plan import PM_HEADER_SEQUENCE


class PMRootInsertConflict(RuntimeError):
    pass


def padded(row, width=22):
    if len(row) > width:
        raise PMRootInsertConflict("PM_ROW_WIDTH_CONFLICT")
    return [str(v) if v is not None else "" for v in row] + [
        ""
    ] * (width - len(row))



def source_owned_root_matches(existing, expected):
    """Compare inserted ROOT data without overwriting PM categories.

    Column I (index 8) is human-managed. Every other A:V value
    must match the originally exported ROOT row.
    """
    existing = padded(existing)
    expected = padded(expected)
    return all(
        existing[index] == expected[index]
        for index in range(22)
        if index != 8
    )

class GuardedRootAppender:
    def __init__(
        self,
        service,
        spreadsheet_id,
        tab,
        *,
        authorized_spreadsheet_id,
        authorized_tab,
    ):
        if (
            not spreadsheet_id
            or not tab
            or spreadsheet_id != authorized_spreadsheet_id
            or tab != authorized_tab
        ):
            raise PermissionError("PM_ROOT_DESTINATION_NOT_AUTHORIZED")

        self.service = service
        self.spreadsheet_id = spreadsheet_id
        self.tab = tab

    def read(self):
        response = (
            self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{self.tab}'!A1:V",
                valueRenderOption="FORMULA",
            ).execute()
        )
        return [
            padded(row)
            for row in response.get("values", [])
        ]

    def sheet_id(self):
        response = self.service.spreadsheets().get(
            spreadsheetId=self.spreadsheet_id,
            fields="sheets(properties(sheetId,title))",
        ).execute()

        matches = [
            x["properties"]["sheetId"]
            for x in response.get("sheets", [])
            if x["properties"]["title"] == self.tab
        ]

        if len(matches) != 1:
            raise PMRootInsertConflict("PM_TAB_NOT_UNIQUE_OR_MISSING")

        return matches[0]

    def apply(self, new_row, *, allow_writes=False):
        desired = padded(new_row)
        root_id = desired[14].strip()

        if not root_id:
            raise ValueError("NEW_ROOT_ID_REQUIRED")

        before = self.read()

        if not before or before[0] != list(PM_HEADER_SEQUENCE):
            raise PMRootInsertConflict("PM_HEADER_MISMATCH")

        existing = {}

        for index, row in enumerate(before[1:], start=2):
            identity = row[14].strip()
            if not identity:
                if any(row):
                    raise PMRootInsertConflict(
                        f"UNIDENTIFIED_PM_ROW_AT_{index}"
                    )
                continue

            if identity in existing:
                raise PMRootInsertConflict(
                    f"DUPLICATE_PM_ROOT_ID_{identity}"
                )

            existing[identity] = row

        if root_id in existing:
            if not source_owned_root_matches(
                existing[root_id], desired
            ):
                raise PMRootInsertConflict(
                    "EXISTING_ROOT_CONTENT_CONFLICT"
                )

            return {
                "verified": True,
                "action": "ALREADY_PRESENT",
                "root_id": root_id,
                "written": False,
            }

        if not allow_writes:
            return {
                "verified": False,
                "action": "INSERT_CANDIDATE",
                "root_id": root_id,
                "written": False,
            }

        # Recheck all source-owned and human-owned visible PM cells
        # before attempting the atomic append.
        if self.read() != before:
            raise PMRootInsertConflict(
                "PM_CHANGED_BEFORE_INSERT"
            )

        sheet_id = self.sheet_id()

        # Single Sheets appendCells request. String values are
        # literal, not executable formulas.
        cells = [
            {"userEnteredValue": {"stringValue": value}}
            if value else {}
            for value in desired
        ]

        self.service.spreadsheets().batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body={
                "requests": [{
                    "appendCells": {
                        "sheetId": sheet_id,
                        "rows": [{"values": cells}],
                        "fields": "userEnteredValue",
                    },
                }],
            },
        ).execute()

        after = self.read()

        old_ids = {
            row[14] for row in before[1:] if row[14]
        }
        new_rows = [
            row for row in after[1:]
            if row[14] == root_id
        ]

        if len(new_rows) != 1 or new_rows[0] != desired:
            raise PMRootInsertConflict(
                "PM_ROOT_INSERT_READBACK_FAILED"
            )

        if len(after) < len(before) + 1:
            raise PMRootInsertConflict(
                "PM_ROOT_ROW_COUNT_VERIFICATION_FAILED"
            )

        # No prior PM row can disappear or change.
        # Row-number preservation is also required.
        if after[:len(before)] != before:
            raise PMRootInsertConflict(
                "EXISTING_PM_ROWS_CHANGED_DURING_INSERT"
            )

        after_ids = {
            row[14] for row in after[1:] if row[14]
        }

        if after_ids != old_ids | {root_id}:
            raise PMRootInsertConflict(
                "PM_ROOT_SET_VERIFICATION_FAILED"
            )

        return {
            "verified": True,
            "action": "INSERTED",
            "root_id": root_id,
            "written": True,
        }
