"""Google Sheets-backed V2 checkpoint adapter.

Writes are disabled by default. The target tab must already
exist with the exact schema. No implicit tab creation.
"""

from __future__ import annotations

from typing import Any

from v2_pm_checkpoint_store import (
    PM_EXPORT_HEADERS,
    deserialize_checkpoint,
    plan_checkpoint_storage,
    serialize_checkpoint,
)

CHECKPOINT_TAB = "_PM_Exports_V2"

ALLOWED_TRANSITIONS = {
    "EXPORT_PENDING": {"EXPORT_PENDING", "EXPORTING"},
    "EXPORTING": {
        "EXPORTING", "EXPORT_PENDING", "EXPORT_VERIFIED"
    },
    "EXPORT_VERIFIED": {
        "EXPORT_VERIFIED", "NOTIFICATION_PENDING", "COMPLETED"
    },
    "NOTIFICATION_PENDING": {
        "NOTIFICATION_PENDING", "COMPLETED", "DELIVERY_UNCERTAIN"
    },
    "DELIVERY_UNCERTAIN": {"DELIVERY_UNCERTAIN"},
    "COMPLETED": {"COMPLETED"},
}


def read_checkpoint_table(
    sheets: Any,
    *,
    tab: str = CHECKPOINT_TAB,
) -> list[list[Any]]:
    """Read and validate checkpoint table, including headers."""
    values = sheets.get_all_values(tab, refresh=True)

    if not values:
        raise ValueError(
            f"Checkpoint tab {tab!r} is missing or empty. "
            "Provision its headers before enabling writes."
        )

    if list(values[0]) != PM_EXPORT_HEADERS:
        raise ValueError(
            "Checkpoint tab schema mismatch. Refusing access."
        )

    data = [list(row) for row in values[1:]]
    seen = set()

    for row in data:
        record = deserialize_checkpoint(row)
        key = record["export_id"]

        if key in seen:
            raise ValueError(
                f"Duplicate persisted Export ID: {key}"
            )
        seen.add(key)

    return data


def get_checkpoint(
    sheets: Any,
    export_id: str,
    *,
    tab: str = CHECKPOINT_TAB,
) -> dict[str, Any] | None:
    """Read one checkpoint without modifying storage."""
    key = str(export_id).strip()
    if not key:
        raise ValueError("Export ID is required")

    for row in read_checkpoint_table(sheets, tab=tab):
        record = deserialize_checkpoint(row)
        if record["export_id"] == key:
            return record

    return None


def persist_checkpoint(
    sheets: Any,
    checkpoint: dict[str, Any],
    *,
    allow_writes: bool = False,
    tab: str = CHECKPOINT_TAB,
) -> dict[str, Any]:
    """Persist a checkpoint and verify it by reading back.

    Requires explicit write authorization. Caller must prevent
    concurrent writers for the same Export ID. Google Sheets
    does not offer an atomic compare-and-swap through this API.
    """
    rows = read_checkpoint_table(sheets, tab=tab)
    plan = plan_checkpoint_storage(rows, checkpoint)

    result = {
        "action": plan["action"],
        "export_id": checkpoint["export_id"],
        "written": False,
        "verified": False,
    }

    if plan["action"] == "NOOP":
        result["verified"] = True
        return result

    if not allow_writes:
        return result

    if plan["action"] == "UPDATE_CANDIDATE":
        old = deserialize_checkpoint(
            rows[plan["row_number"] - 2]
        )
        old_state = old["state"]
        new_state = checkpoint["state"]

        if new_state not in ALLOWED_TRANSITIONS[old_state]:
            raise ValueError(
                f"Invalid persisted transition: "
                f"{old_state} -> {new_state}"
            )

    # Re-read immediately before mutation. This detects some
    # concurrent changes, but it is not an atomic lock.
    latest = read_checkpoint_table(sheets, tab=tab)
    if latest != rows:
        raise RuntimeError(
            "Checkpoint table changed since planning. "
            "Retry after reloading."
        )

    if plan["action"] == "INSERT_CANDIDATE":
        sheets.append_rows(tab, [plan["serialized_row"]])
    elif plan["action"] == "UPDATE_CANDIDATE":
        sheets.batch_update_rows(
            tab,
            [(plan["row_number"], plan["serialized_row"])]
        )
    else:
        raise ValueError("Unexpected checkpoint plan action")

    result["written"] = True

    stored = get_checkpoint(
        sheets, checkpoint["export_id"], tab=tab
    )
    expected = deserialize_checkpoint(
        serialize_checkpoint(checkpoint)
    )

    if stored != expected:
        raise RuntimeError(
            "Checkpoint write verification failed. "
            "Do not advance export or send notifications."
        )

    result["verified"] = True
    return result
