"""Source-verified, non-writing V2 PM delta planning."""

from __future__ import annotations

from typing import Any


def _value(value: Any) -> str:
    return str(value if value is not None else "")


def _index(rows, label):
    result = {}
    for row in rows:
        key = _value(row.get("Root Entry ID")).strip()
        if not key or key in result:
            raise ValueError(
                f"{label}: blank or duplicate Root Entry ID"
            )
        result[key] = row
    return result


def plan_verified_source_delta(
    existing_pm: list[dict[str, Any]],
    previous_projection: list[dict[str, Any]],
    updated_projection: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create plans only; never mutate rows or call APIs.

    Verified comment update requires:
      1. Previous and updated source values differ.
      2. The existing PM value equals the previous source.
    Replies, names, categories and removals are never
    automatically authorized by this preliminary planner.
    """
    pm = _index(existing_pm, "PM")
    before = _index(previous_projection, "Previous source")
    after = _index(updated_projection, "Updated source")

    if not set(before).issubset(set(pm)):
        raise ValueError(
            "Previous source has IDs missing from PM; "
            "baseline reconciliation required."
        )

    updates = []
    new_candidates = []
    held = []
    historical = []

    for key, current in after.items():
        if key not in before:
            if key in pm:
                held.append({
                    "id": key,
                    "reason": "NEW_SOURCE_ID_ALREADY_IN_PM",
                })
            else:
                new_candidates.append(dict(current))
            continue

        old = before[key]
        existing = pm[key]

        old_comment = _value(old.get("Comment"))
        new_comment = _value(current.get("Comment"))
        pm_comment = _value(existing.get("Comment"))

        if old_comment != new_comment:
            if pm_comment == old_comment:
                updates.append({
                    "root_entry_id": key,
                    "field": "Comment",
                    "expected_pm_value": pm_comment,
                    "new_value": new_comment,
                    "reason": "VERIFIED_SOURCE_COMMENT_CHANGE",
                })
            else:
                held.append({
                    "id": key,
                    "field": "Comment",
                    "reason": "PM_SOURCE_CONFLICT",
                })

        reply_fields = set()
        for row in (old, current):
            reply_fields.update(
                field for field in row
                if field.startswith("Reply ")
            )
        reply_fields.add("Reply Entry IDs")

        if any(
            _value(old.get(field)) != _value(current.get(field))
            for field in reply_fields
        ):
            held.append({
                "id": key,
                "reason": "REPLY_CHANGE_NEEDS_ID_AWARE_PLANNER",
            })

        # Existing authors, categories and metadata are
        # deliberately excluded from authorized writes.

    for key in before:
        if key not in after:
            historical.append(key)

    return {
        "mode": "DRY_RUN",
        "verified_cell_update_candidates": updates,
        "new_root_candidates": new_candidates,
        "held_for_review": held,
        "historical_root_ids": historical,
        "google_write_operations": [],
        "deletion_operations": [],
    }
