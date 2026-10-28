"""Guarded, cell-level Google Sheets writer for PrOps V2.

Explicit destination authorization, identity checks, conflict detection,
targeted writes, and read-back verification.

Important: Google Sheets has no atomic compare-and-swap for values.
Use a single writer per output document to prevent concurrent writers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


CELL_RE = re.compile(r"^([A-Z]+)([1-9][0-9]*)$")


class PMWriteConflict(RuntimeError):
    pass


class PMWriteVerificationError(RuntimeError):
    pass


@dataclass(frozen=True)
class CellChange:
    root_id: str
    cell: str
    expected_value: str
    new_value: str


def column_index(letters):
    result = 0
    for char in letters:
        result = result * 26 + ord(char) - ord("A") + 1
    return result - 1


def parse_cell(cell):
    match = CELL_RE.fullmatch(cell)
    if not match:
        raise ValueError(f"Invalid cell address: {cell!r}")
    return column_index(match.group(1)), int(match.group(2))


class GuardedPMWriter:
    def __init__(
        self, service, spreadsheet_id, tab,
        *, authorized_spreadsheet_id,
        authorized_tab,
        column_mapping=None,
    ):
        if (
            spreadsheet_id != authorized_spreadsheet_id
            or tab != authorized_tab
        ):
            raise PermissionError(
                "Destination is not explicitly authorized"
            )

        if not spreadsheet_id or not tab:
            raise ValueError("Missing destination")

        self.service = service
        self.spreadsheet_id = spreadsheet_id
        self.tab = tab
        self.column_mapping = column_mapping

    def read_cell(self, cell, *, render="FORMATTED_VALUE"):
        result = self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"'{self.tab}'!{cell}",
            valueRenderOption=render,
        ).execute()
        values = result.get("values", [])
        return (
            str(values[0][0])
            if values and values[0] else ""
        )

    def root_cell(self, row):
        if self.column_mapping is None:
            return f"O{row}"
        return self.column_mapping.physical_cell(f"O{row}")

    def verify_live_headers(self):
        if self.column_mapping is None:
            return
        response = self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"'{self.tab}'!A1:{self.column_mapping.last_column}1",
            valueRenderOption="FORMATTED_VALUE",
        ).execute()
        self.column_mapping.check_headers(response.get("values", []))

    def apply(self, changes, *, allow_writes=False):
        self.verify_live_headers()
        if len({x.cell for x in changes}) != len(changes):
            raise ValueError("Duplicate target cells")

        pending = []
        already_applied = []

        # Check ALL intended changes before writing ANY.
        for change in changes:
            col, row = parse_cell(change.cell)

            if row < 2:
                raise ValueError("Header cells are protected")

            permitted = (
                set(self.column_mapping.writable_positions)
                if self.column_mapping is not None
                else {4, 5, 6, 7, 21}
            )
            if col not in permitted:
                raise ValueError(
                    f"Unapproved output column: {change.cell}"
                )

            root = self.read_cell(self.root_cell(row))
            if root != change.root_id:
                raise PMWriteConflict(
                    f"ROOT_ID_CONFLICT at {change.cell}"
                )

            actual = self.read_cell(change.cell)
            formula = self.read_cell(
                change.cell, render="FORMULA"
            )

            if formula.startswith("="):
                raise PMWriteConflict(
                    f"FORMULA_PROTECTED at {change.cell}"
                )

            if actual == change.new_value:
                already_applied.append(change.cell)
            elif actual == change.expected_value:
                pending.append(change)
            else:
                raise PMWriteConflict(
                    f"MANUAL_EDIT_CONFLICT at {change.cell}: "
                    f"expected {change.expected_value!r}; "
                    f"found {actual!r}"
                )

        result = {
            "pending": [x.cell for x in pending],
            "already_applied": already_applied,
            "written": [],
            "verified": not pending,
        }

        if not allow_writes or not pending:
            return result

        # Recheck every target immediately before the write.
        for change in pending:
            _, row = parse_cell(change.cell)
            if self.read_cell(self.root_cell(row)) != change.root_id:
                raise PMWriteConflict(
                    f"ROOT_MOVED at {change.cell}"
                )
            if self.read_cell(change.cell) != change.expected_value:
                raise PMWriteConflict(
                    f"CELL_CHANGED at {change.cell}"
                )
            if self.read_cell(
                change.cell, render="FORMULA"
            ).startswith("="):
                raise PMWriteConflict(
                    f"FORMULA_PROTECTED at {change.cell}"
                )

        self.verify_live_headers()
        self.service.spreadsheets().values().batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body={
                "valueInputOption": "RAW",
                "data": [
                    {
                        "range": f"'{self.tab}'!{x.cell}",
                        "values": [[x.new_value]],
                    }
                    for x in pending
                ],
            },
        ).execute()

        # Verify every written cell, including its ROOT identity.
        for change in pending:
            _, row = parse_cell(change.cell)
            if (
                self.read_cell(self.root_cell(row)) != change.root_id
                or self.read_cell(change.cell) != change.new_value
            ):
                raise PMWriteVerificationError(
                    f"READBACK_FAILED at {change.cell}"
                )

        result["written"] = [x.cell for x in pending]
        result["verified"] = True
        return result
