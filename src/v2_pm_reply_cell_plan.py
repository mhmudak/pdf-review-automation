"""Read-only, retry-aware PM reply cell planning.

Supports one new reply per ROOT per planning operation.
Both the visible reply and technical ID cell are checked.
No Google APIs or write operations.
"""

from __future__ import annotations

from typing import Any

from v2_pm_cell_plan import PM_HEADER_SEQUENCE
from v2_pm_reply_delta import reply_ids


ROOT_INDEX = 14
IDS_INDEX = 21


def text(value: Any) -> str:
    return "" if value is None else str(value)


def row_cell(row: list[Any], index: int) -> str:
    return text(row[index]) if index < len(row) else ""


def index_pm_rows(sheet_values: list[list[Any]]):
    if not sheet_values:
        raise ValueError("Empty PM sheet")

    if [text(x).strip() for x in sheet_values[0]] != PM_HEADER_SEQUENCE:
        raise ValueError("PM sheet schema mismatch")

    found = {}
    for number, row in enumerate(sheet_values[1:], start=2):
        key = row_cell(row, ROOT_INDEX).strip()
        if not key or key in found:
            raise ValueError("Missing or duplicate PM ROOT ID")
        found[key] = (number, row)
    return found


def plan_pm_reply_cells(
    sheet_values: list[list[Any]],
    previous_projection: list[dict[str, Any]],
    reply_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Plan missing cells for verified new replies.

    Rechecks PM reply IDs and text against the previous
    source. Never overwrites an occupied conflicting cell.
    """
    locations = index_pm_rows(sheet_values)

    previous = {}
    for row in previous_projection:
        key = text(row.get("Root Entry ID")).strip()
        if not key or key in previous:
            raise ValueError("Invalid previous projection ROOT IDs")
        previous[key] = row

    updates = []
    already_applied = []
    conflicts = []
    seen_roots = set()

    for candidate in reply_candidates:
        root = text(candidate.get("root_entry_id")).strip()
        new_id = text(candidate.get("reply_entry_id")).strip()
        field = text(candidate.get("field")).strip()
        new_text = text(candidate.get("new_value"))
        reason = candidate.get("reason")

        if (
            not root or not new_id
            or reason != "VERIFIED_NEW_REPLY_ID"
            or candidate.get("expected_pm_value") != ""
        ):
            raise ValueError("Unverified reply candidate")

        if root in seen_roots:
            raise ValueError(
                "Only one new reply per ROOT per operation"
            )
        seen_roots.add(root)

        if root not in locations or root not in previous:
            conflicts.append((root, "ROOT_OR_BASELINE_MISSING"))
            continue

        row_number, pm_row = locations[root]
        old_ids = reply_ids(previous[root])
        position = len(old_ids) + 1

        if position > 3:
            conflicts.append((root, "DYNAMIC_REPLY_COLUMN_REQUIRED"))
            continue

        if field != f"Reply {position}" or not new_text:
            raise ValueError("Reply position or text is invalid")

        current_ids = reply_ids({
            "Reply Entry IDs": row_cell(pm_row, IDS_INDEX)
        })

        expected_ids = old_ids
        resulting_ids = old_ids + [new_id]

        if current_ids not in (expected_ids, resulting_ids):
            conflicts.append((root, "REPLY_ID_CONFLICT"))
            continue

        visible_index = 4 + position
        actual_text = row_cell(pm_row, visible_index)

        if actual_text not in ("", new_text):
            conflicts.append((root, "REPLY_TEXT_CONFLICT"))
            continue

        if actual_text == "":
            updates.append({
                "root_entry_id": root,
                "cell": f"{chr(69 + position)}{row_number}",
                "expected_value": "",
                "new_value": new_text,
                "field": field,
            })
        else:
            already_applied.append(f"{field}:{root}")

        if current_ids == expected_ids:
            existing_raw = row_cell(pm_row, IDS_INDEX)
            separator = " | " if "|" in existing_raw else " | "
            new_raw = separator.join(resulting_ids)

            updates.append({
                "root_entry_id": root,
                "cell": f"V{row_number}",
                "expected_value": existing_raw,
                "new_value": new_raw,
                "field": "Reply Entry IDs",
            })
        else:
            already_applied.append(f"Reply Entry IDs:{root}")

    return {
        "mode": "DRY_RUN",
        "cell_update_candidates": updates,
        "already_applied": already_applied,
        "conflicts": conflicts,
        "google_write_operations": [],
        "deletion_operations": [],
    }
