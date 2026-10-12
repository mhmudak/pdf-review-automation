from __future__ import annotations

import time
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from google_auth import get_credentials


DATABASE_HEADERS = [
    "Annotation Key", "Reviewer", "Raw Author", "PDF Name", "Drive File ID",
    "Drive Link", "PDF SHA256", "PDF Page", "Book Page", "Page Mapping Method",
    "Page Mapping Confidence", "Annotation Type", "Category", "Comment Original",
    "Selected Text", "Created Date", "Modified Date", "Annotation ID",
    "Parent Annotation ID", "Subject", "Coordinates", "XRef", "Active",
    "Source State", "First Seen", "Last Seen",
]

FILES_HEADERS = [
    "Drive File ID", "PDF Name", "Drive Link", "Modified Time", "Size Bytes",
    "PDF SHA256", "Reviewer", "Status", "Pages", "Annotations Found", "New",
    "Updated", "Unchanged", "Skipped Empty", "Processed At", "Message / Error",
]

NEEDS_REVIEW_HEADERS = [
    "Created At", "Drive File ID", "PDF Name", "Issue Type", "Reviewer Candidate",
    "Raw Author", "PDF Page", "Book Page Candidate", "Comment", "Reason", "Status",
    "Resolution",
]

VISIBLE_HEADERS = [
    "PDF Name", "PDF Drive Link", "Page", "Comment", "Category",
    "Author", "Created Date", "Last Modified", "Resolved?", "Replies", "Comment ID", "Annotation Type",
]

DOCUMENT_HEADERS = [
    "Document Key",
    "Document Name",
    "Output Tab",
    "Master Version",
    "Current Version ID",
    "Current Drive File ID",
    "Current PDF SHA256",
    "Current Modified Time",
    "Status",
    "Last Processed",
]


ENTRY_V2_HEADERS = [
    "Entry Key",
    "Document Key",
    "Version ID",
    "Drive File ID",
    "PDF Name",
    "Drive Link",
    "PDF SHA256",

    "Entry ID",
    "Parent Entry ID",
    "Root Entry ID",
    "Entry Type",
    "Reply Depth",

    "Raw Author",
    "Canonical Author",
    "Author Status",
    "Author Resolution Method",
    "Author Rule ID",

    "PDF Page",
    "Book Page",
    "Page Mapping Method",
    "Page Mapping Confidence",

    "Annotation Type",
    "Relation Type",
    "Category",
    "Content",
    "Selected Text",

    "Created Date",
    "Modified Date",

    "Coordinates",
    "XRef",

    "Active",
    "Source State",

    "First Seen",
    "Last Seen",
]


AUTHOR_RULE_HEADERS = [
    "Rule ID",
    "Scope",
    "Document Key",
    "Version ID",
    "Root Entry ID",
    "Entry ID",
    "Raw Author",
    "Canonical Author",
    "Status",
    "Approved By",
    "Approved At",
    "Notes",
]

class SheetsAdapter:
    def __init__(self, spreadsheet_id: str) -> None:
        self.spreadsheet_id = spreadsheet_id
        self.service = build(
            "sheets",
            "v4",
            credentials=get_credentials(),
            cache_discovery=False,
        )

        # Per-execution caches only.
        # Nothing is persisted between Cloud Run executions.
        self._metadata_cache: dict[str, Any] | None = None
        self._values_cache: dict[str, list[list[Any]]] = {}
        self._hidden_columns_cache: set[
            tuple[str, tuple[tuple[int, int], ...]]
        ] = set()

    def _execute(self, request: Any, max_retries: int = 6) -> Any:
        for attempt in range(max_retries + 1):
            try:
                return request.execute()

            except HttpError as exc:
                status = getattr(exc.resp, "status", None)

                if (
                    status not in {429, 500, 502, 503, 504}
                    or attempt >= max_retries
                ):
                    raise

                delay = min(2 ** attempt, 32)
                time.sleep(delay)

        raise RuntimeError("Retry loop exited unexpectedly")

    def _end_column(self, sheet: str) -> str:
        if sheet == "_Database":
            return "Z"

        if sheet == "_Files":
            return "P"

        if sheet == "_Needs Review":
            return "L"

        if sheet == "_Config":
            return "D"

        if sheet == "_Documents":
            return "J"

        if sheet == "_Entries_V2":
            return "AH"

        if sheet == "_Author Rules":
            return "K"

        # Reviewer-facing tabs use 12 columns.
        return "L"

    def metadata(self, refresh: bool = False) -> dict[str, Any]:
        if self._metadata_cache is not None and not refresh:
            return self._metadata_cache

        self._metadata_cache = self._execute(
            self.service.spreadsheets().get(
                spreadsheetId=self.spreadsheet_id
            )
        )

        return self._metadata_cache

    def sheet_titles(self) -> set[str]:
        return {
            sheet["properties"]["title"]
            for sheet in self.metadata().get("sheets", [])
        }

    def ensure_sheet(self, title: str, hidden: bool = False) -> None:
        if title in self.sheet_titles():
            return

        self._execute(
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={
                    "requests": [
                        {
                            "addSheet": {
                                "properties": {
                                    "title": title,
                                    "hidden": hidden,
                                }
                            }
                        }
                    ]
                },
            )
        )

        # Spreadsheet structure changed.
        self._metadata_cache = None

    def ensure_headers(self, sheet: str, headers: list[str]) -> None:
        self.ensure_sheet(
            sheet,
            hidden=sheet in {"_Database", "_Files", "_Config", "_Documents", "_Entries_V2", "_Author Rules",},
        )

        current = self._execute(
            self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{sheet}'!A1:{self._end_column(sheet)}1",
            )
        ).get("values", [[]])

        first = current[0] if current else []

        if first[: len(headers)] == headers:
            return

        self._execute(
            self.service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{sheet}'!A1",
                valueInputOption="RAW",
                body={"values": [headers]},
            )
        )

        # Header changed: invalidate any cached content.
        self._values_cache.pop(sheet, None)

    def get_all_values(
        self,
        sheet: str,
        refresh: bool = False,
    ) -> list[list[Any]]:

        if sheet in self._values_cache and not refresh:
            return self._values_cache[sheet]

        end_column = self._end_column(sheet)

        values = self._execute(
            self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{sheet}'!A:{end_column}",
            )
        ).get("values", [])

        self._values_cache[sheet] = values

        return values

    def batch_get_values(
        self,
        sheets: list[str],
        refresh: bool = False,
    ) -> dict[str, list[list[Any]]]:
        """
        Fetch multiple sheet ranges in one Google Sheets API
        values.batchGet request.

        Results are cached for the rest of this execution.
        """

        if not sheets:
            return {}

        output: dict[
            str,
            list[list[Any]],
        ] = {}

        missing: list[str] = []

        for sheet in sheets:
            if (
                not refresh
                and sheet in self._values_cache
            ):
                output[sheet] = (
                    self._values_cache[sheet]
                )
            else:
                missing.append(sheet)

        if missing:
            ranges = [
                (
                    f"'{sheet}'!"
                    f"A:{self._end_column(sheet)}"
                )
                for sheet in missing
            ]

            response = self._execute(
                self.service
                .spreadsheets()
                .values()
                .batchGet(
                    spreadsheetId=(
                        self.spreadsheet_id
                    ),
                    ranges=ranges,
                    majorDimension="ROWS",
                )
            )

            value_ranges = response.get(
                "valueRanges",
                [],
            )

            for index, sheet in enumerate(
                missing
            ):
                values = []

                if index < len(value_ranges):
                    values = (
                        value_ranges[index]
                        .get("values", [])
                    )

                self._values_cache[
                    sheet
                ] = values

                output[sheet] = values

        return {
            sheet: output.get(
                sheet,
                [],
            )
            for sheet in sheets
        }

    def append_rows(
        self,
        sheet: str,
        rows: list[list[Any]],
    ) -> None:

        if not rows:
            return

        self._execute(
            self.service.spreadsheets().values().append(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{sheet}'!A1",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": rows},
            )
        )

        # Keep the local cache synchronized with successful writes.
        if sheet in self._values_cache:
            self._values_cache[sheet].extend(
                [list(row) for row in rows]
            )

    def update_row(
        self,
        sheet: str,
        row_number: int,
        row: list[Any],
    ) -> None:

        self._execute(
            self.service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{sheet}'!A{row_number}",
                valueInputOption="RAW",
                body={"values": [row]},
            )
        )

        if sheet in self._values_cache:
            cache = self._values_cache[sheet]

            while len(cache) < row_number:
                cache.append([])

            cache[row_number - 1] = list(row)

    def batch_update_rows(
        self,
        sheet: str,
        updates: list[tuple[int, list[Any]]],
    ) -> None:

        if not updates:
            return

        data = [
            {
                "range": f"'{sheet}'!A{row_number}",
                "values": [row],
            }
            for row_number, row in updates
        ]

        self._execute(
            self.service.spreadsheets().values().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={
                    "valueInputOption": "RAW",
                    "data": data,
                },
            )
        )

        if sheet in self._values_cache:
            cache = self._values_cache[sheet]

            for row_number, row in updates:
                while len(cache) < row_number:
                    cache.append([])

                cache[row_number - 1] = list(row)

    def key_to_row(
        self,
        sheet: str,
        key_col: int = 0,
    ) -> dict[str, int]:

        values = self.get_all_values(sheet)

        output: dict[str, int] = {}

        for i, row in enumerate(values[1:], start=2):
            if (
                len(row) > key_col
                and str(row[key_col]).strip()
            ):
                output[str(row[key_col]).strip()] = i

        return output

    def hide_columns(
        self,
        sheet: str,
        column_ranges: list[tuple[int, int]],
    ) -> None:
        cache_key = (
            sheet,
            tuple(column_ranges),
        )

        if cache_key in self._hidden_columns_cache:
            return

        metadata = self.metadata()

        sheet_id = None

        for item in metadata.get("sheets", []):
            properties = item.get(
                "properties",
                {},
            )

            if properties.get("title") == sheet:
                sheet_id = properties.get(
                    "sheetId"
                )
                break

        if sheet_id is None:
            raise ValueError(
                f"Sheet not found: {sheet}"
            )

        requests = []

        for start_index, end_index in column_ranges:
            requests.append(
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "COLUMNS",
                            "startIndex": start_index,
                            "endIndex": end_index,
                        },
                        "properties": {
                            "hiddenByUser": True,
                        },
                        "fields": "hiddenByUser",
                    }
                }
            )

        if not requests:
            return

        self._execute(
            self.service
            .spreadsheets()
            .batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={
                    "requests": requests
                },
            )
        )

        self._hidden_columns_cache.add(cache_key)

    def get_range_values(
        self,
        sheet: str,
        cell_range: str,
    ) -> list[list[Any]]:
        return self._execute(
            self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{sheet}'!{cell_range}",
            )
        ).get("values", [])

    def clear_range(
        self,
        sheet: str,
        cell_range: str,
    ) -> None:
        self._execute(
            self.service.spreadsheets().values().clear(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{sheet}'!{cell_range}",
                body={},
            )
        )

        self._values_cache.pop(
            sheet,
            None,
        )
