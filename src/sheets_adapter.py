from __future__ import annotations

from typing import Any

from googleapiclient.discovery import build

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
    "PDF Name", "PDF Drive Link", "Page", "Comment", "Annotation Type",
    "Author", "Created Date", "Last Modified", "Resolved?", "Replies", "Comment ID",
]


class SheetsAdapter:
    def __init__(self, spreadsheet_id: str) -> None:
        self.spreadsheet_id = spreadsheet_id
        self.service = build("sheets", "v4", credentials=get_credentials(), cache_discovery=False)

    def metadata(self) -> dict[str, Any]:
        return self.service.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()

    def sheet_titles(self) -> set[str]:
        return {s["properties"]["title"] for s in self.metadata().get("sheets", [])}

    def ensure_sheet(self, title: str, hidden: bool = False) -> None:
        if title in self.sheet_titles():
            return
        self.service.spreadsheets().batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": title, "hidden": hidden}}}]},
        ).execute()

    def ensure_headers(self, sheet: str, headers: list[str]) -> None:
        # _Needs Review intentionally remains visible; other technical sheets may be hidden later.
        self.ensure_sheet(sheet, hidden=sheet in {"_Database", "_Files", "_Config"})
        current = self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"'{sheet}'!1:1",
        ).execute().get("values", [[]])
        first = current[0] if current else []
        if first[: len(headers)] == headers:
            return
        self.service.spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id,
            range=f"'{sheet}'!A1",
            valueInputOption="RAW",
            body={"values": [headers]},
        ).execute()

    def get_all_values(self, sheet: str) -> list[list[Any]]:
        return self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"'{sheet}'!A:ZZ",
        ).execute().get("values", [])

    def append_rows(self, sheet: str, rows: list[list[Any]]) -> None:
        if not rows:
            return
        self.service.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id,
            range=f"'{sheet}'!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": rows},
        ).execute()

    def update_row(self, sheet: str, row_number: int, row: list[Any]) -> None:
        self.service.spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id,
            range=f"'{sheet}'!A{row_number}",
            valueInputOption="RAW",
            body={"values": [row]},
        ).execute()

    def key_to_row(self, sheet: str, key_col: int = 0) -> dict[str, int]:
        values = self.get_all_values(sheet)
        out: dict[str, int] = {}
        for i, row in enumerate(values[1:], start=2):
            if len(row) > key_col and str(row[key_col]).strip():
                out[str(row[key_col]).strip()] = i
        return out
