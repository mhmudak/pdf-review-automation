"""Non-writing, identity-aware planning for V2 PM replies."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any


REPLY_COLUMN = re.compile(r"^Reply ([1-9][0-9]*)$")


def text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def reply_ids(row: dict[str, Any]) -> list[str]:
    value = text(row.get("Reply Entry IDs"))
    if not value:
        return []
    ids = [
        part.strip()
        for part in value.replace("|", ",").split(",")
    ]
    if any(not part for part in ids) or len(ids) != len(set(ids)):
        raise ValueError("Malformed or duplicate Reply Entry IDs")
    return ids


def index(rows: list[dict[str, Any]], label: str):
    result = {}
    for row in rows:
        key = text(row.get("Root Entry ID"))
        if not key or key in result:
            raise ValueError(f"{label}: missing or duplicate ROOT ID")
        result[key] = row
    return result


def validate_global_ids(rows, label):
    all_ids = [
        value
        for row in rows
        for value in reply_ids(row)
    ]
    duplicates = [
        value for value, count in Counter(all_ids).items()
        if count > 1
    ]
    if duplicates:
        raise ValueError(
            f"{label}: reply ID appears in multiple ROOT rows"
        )


def plan_reply_changes(
    existing_pm: list[dict[str, Any]],
    previous_projection: list[dict[str, Any]],
    updated_projection: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return candidates only, never write Google Sheets.

    Existing displayed replies are preserved. New replies
    must extend the established ordered ID sequence.
    """
    pm = index(existing_pm, "PM")
    before = index(previous_projection, "Previous source")
    after = index(updated_projection, "Updated source")

    for label, rows in (
        ("PM", existing_pm),
        ("Previous", previous_projection),
        ("Updated", updated_projection),
    ):
        validate_global_ids(rows, label)

    candidates = []
    held = []

    for root_id, new_row in after.items():
        if root_id not in before or root_id not in pm:
            continue  # New ROOTs belong to the ROOT planner.

        old_row = before[root_id]
        pm_row = pm[root_id]

        old_ids = reply_ids(old_row)
        new_ids = reply_ids(new_row)
        pm_ids = reply_ids(pm_row)

        if pm_ids != old_ids:
            held.append({
                "root_entry_id": root_id,
                "reason": "PM_REPLY_ID_BASELINE_CONFLICT",
            })
            continue

        if new_ids == old_ids:
            changed = any(
                text(old_row.get(f"Reply {i}"))
                != text(new_row.get(f"Reply {i}"))
                for i in range(1, len(old_ids) + 1)
            )
            if changed:
                held.append({
                    "root_entry_id": root_id,
                    "reason": "EXISTING_REPLY_EDIT_REQUIRES_VERIFICATION",
                })
            continue

        if new_ids[:len(old_ids)] != old_ids:
            held.append({
                "root_entry_id": root_id,
                "reason": "REPLY_REMOVAL_OR_REORDER",
            })
            continue

        if any(
            text(old_row.get(f"Reply {i}"))
            != text(new_row.get(f"Reply {i}"))
            for i in range(1, len(old_ids) + 1)
        ):
            held.append({
                "root_entry_id": root_id,
                "reason": "OLD_REPLY_CHANGED_WHILE_APPENDING",
            })
            continue

        additions = []
        conflict = False
        for position in range(len(old_ids) + 1, len(new_ids) + 1):
            field = f"Reply {position}"
            if (
                text(pm_row.get(field))
                or not text(new_row.get(field))
            ):
                conflict = True
                break
            additions.append({
                "root_entry_id": root_id,
                "reply_entry_id": new_ids[position - 1],
                "field": field,
                "expected_pm_value": "",
                "new_value": text(new_row[field]),
                "reason": "VERIFIED_NEW_REPLY_ID",
            })

        if conflict:
            held.append({
                "root_entry_id": root_id,
                "reason": "NEW_REPLY_TARGET_CONFLICT",
            })
        else:
            candidates.extend(additions)

    return {
        "mode": "DRY_RUN",
        "new_reply_cell_candidates": candidates,
        "held_for_review": held,
        "google_write_operations": [],
        "deletion_operations": [],
    }
