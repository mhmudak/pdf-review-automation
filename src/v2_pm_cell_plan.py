"""PrOps V2: positional, non-writing PM cell update planner.

Uses the existing 22-column legacy PM layout.
Never rewrites full rows, deletes data, or calls Google APIs.
"""

from __future__ import annotations

from typing import Any


PM_COLUMNS = {
    "Book Page": "A",
    "PDF Page": "B",
    "Author": "C",
    "PDF Date (Last Modified)": "D",
    "Comment": "E",
    "Reply 1": "F",
    "Reply 2": "G",
    "Reply 3": "H",
    "Category": "I",
    "Selected Text": "J",
    "Annotation Type": "K",
    "PDF Link": "L",
    "Technical PDF Page": "M",
    "Last Modified": "N",
    "Root Entry ID": "O",
    "Entry Key": "P",
    "Version ID": "Q",
    "Drive File ID": "R",
    "PDF SHA256": "S",
    "Original Created Date": "T",
    "Original Modified Date": "U",
    "Reply Entry IDs": "V",
}

PM_HEADER_SEQUENCE = [
    "Book Page", "PDF Page", "Author",
    "PDF Date (Last Modified)", "Comment",
    "Reply 1", "Reply 2", "Reply 3",
    "Category", "Selected Text", "Annotation Type",
    "PDF Link", "PDF Page", "Last Modified",
    "Root Entry ID", "Entry Key", "Version ID",
    "Drive File ID", "PDF SHA256",
    "Original Created Date", "Original Modified Date",
    "Reply Entry IDs",
]

ROOT_ID_INDEX = 14
COMMENT_INDEX = 4


def value(item: Any) -> str:
    return "" if item is None else str(item)


def plan_pm_comment_cells(
    sheet_values: list[list[Any]],
    verified_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Plan safe comment-cell changes; do not execute them.

    sheet_values includes the header in row 1.
    Supports idempotent retry when a cell already contains
    the verified new value.
    """

    if not sheet_values:
        raise ValueError("PM sheet is empty")

    headers = [
        value(cell).strip() for cell in sheet_values[0]
    ]

    if headers != PM_HEADER_SEQUENCE:
        raise ValueError(
            "PM schema mismatch: refusing positional updates"
        )

    locations = {}

    for sheet_row, row in enumerate(
        sheet_values[1:], start=2
    ):
        root_id = (
            value(row[ROOT_ID_INDEX]).strip()
            if len(row) > ROOT_ID_INDEX else ""
        )

        if not root_id:
            raise ValueError(
                f"Missing ROOT ID at sheet row {sheet_row}"
            )

        if root_id in locations:
            raise ValueError(
                f"Duplicate PM ROOT ID: {root_id}"
            )

        locations[root_id] = (sheet_row, row)

    seen = set()
    updates = []
    already_applied = []
    conflicts = []

    for candidate in verified_candidates:
        root_id = value(
            candidate.get("root_entry_id")
        ).strip()

        field = value(candidate.get("field"))

        if not root_id or field != "Comment":
            raise ValueError(
                "Only verified ROOT Comment candidates "
                "are supported"
            )

        if root_id in seen:
            raise ValueError(
                f"Duplicate change candidate: {root_id}"
            )
        seen.add(root_id)

        if "expected_pm_value" not in candidate:
            raise ValueError("Missing expected PM value")

        if "new_value" not in candidate:
            raise ValueError("Missing new value")

        if candidate.get("reason") != (
            "VERIFIED_SOURCE_COMMENT_CHANGE"
        ):
            raise ValueError(
                "Unverified comment change refused"
            )

        expected = value(candidate["expected_pm_value"])
        replacement = value(candidate["new_value"])

        if root_id not in locations:
            conflicts.append({
                "root_entry_id": root_id,
                "reason": "ROOT_NOT_FOUND",
            })
            continue

        row_number, row = locations[root_id]

        actual = (
            value(row[COMMENT_INDEX])
            if len(row) > COMMENT_INDEX else ""
        )

        if actual == replacement:
            already_applied.append(root_id)
        elif actual != expected:
            conflicts.append({
                "root_entry_id": root_id,
                "reason": "PM_VALUE_CHANGED",
            })
        else:
            updates.append({
                "root_entry_id": root_id,
                "row_number": row_number,
                "cell": f"E{row_number}",
                "expected_value": expected,
                "new_value": replacement,
            })

    return {
        "mode": "DRY_RUN",
        "cell_update_candidates": updates,
        "already_applied_ids": already_applied,
        "conflicts": conflicts,
        "google_write_operations": [],
        "deletion_operations": [],
    }
