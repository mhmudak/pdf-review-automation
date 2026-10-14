"""Validated, non-writing storage planning for V2 export checkpoints."""

from __future__ import annotations

from typing import Any

from v2_pm_checkpoint import STATES


PM_EXPORT_HEADERS = [
    "Export ID",
    "Document Key",
    "Version ID",
    "PDF SHA256",
    "Output Spreadsheet ID",
    "Output Tab",
    "Previous Exported Version ID",
    "State",
    "Attempts",
    "Verified Projection Digest",
    "Error",
    "Notification Key",
]


FIELDS = {
    "Export ID": "export_id",
    "Document Key": "document_key",
    "Version ID": "version_id",
    "PDF SHA256": "pdf_sha256",
    "Output Spreadsheet ID": "output_spreadsheet_id",
    "Output Tab": "output_tab",
    "Previous Exported Version ID": "previous_exported_version_id",
    "State": "state",
    "Attempts": "attempts",
    "Verified Projection Digest": "verified_projection_digest",
    "Error": "error",
    "Notification Key": "notification_key",
}


IDENTITY_FIELDS = (
    "export_id",
    "document_key",
    "version_id",
    "pdf_sha256",
    "output_spreadsheet_id",
    "output_tab",
    "notification_key",
)


def serialize_checkpoint(checkpoint: dict[str, Any]) -> list[str]:
    """Serialize in fixed schema order."""
    if checkpoint.get("state") not in STATES:
        raise ValueError("Unknown checkpoint state")
    if not str(checkpoint.get("export_id") or "").strip():
        raise ValueError("Missing export ID")
    attempts = int(checkpoint.get("attempts", 0))
    if attempts < 0:
        raise ValueError("Negative attempt count")
    return [
        str(checkpoint.get(FIELDS[h], "") or "")
        if h != "Attempts" else str(attempts)
        for h in PM_EXPORT_HEADERS
    ]


def deserialize_checkpoint(row: list[Any]) -> dict[str, Any]:
    if len(row) > len(PM_EXPORT_HEADERS):
        raise ValueError("Unexpected checkpoint columns")
    padded = list(row) + [""] * (
        len(PM_EXPORT_HEADERS) - len(row)
    )
    record = {
        FIELDS[header]: str(value or "")
        for header, value in zip(PM_EXPORT_HEADERS, padded)
    }
    try:
        record["attempts"] = int(
            record["attempts"] or "0"
        )
    except ValueError as exc:
        raise ValueError("Invalid attempt count") from exc

    serialize_checkpoint(record)
    return record


def plan_checkpoint_storage(
    existing_rows: list[list[Any]],
    checkpoint: dict[str, Any],
) -> dict[str, Any]:
    """Plan one insert/update/no-op; absolutely no API calls.

    existing_rows are DATA rows, excluding the header.
    Row numbers include the header, so the first data row is 2.
    """
    serialized = serialize_checkpoint(checkpoint)
    requested = deserialize_checkpoint(serialized)

    found = None
    seen = set()

    for number, row in enumerate(existing_rows, start=2):
        stored = deserialize_checkpoint(row)
        key = stored["export_id"]

        if key in seen:
            raise ValueError("Duplicate stored export ID")
        seen.add(key)

        if key == requested["export_id"]:
            found = (number, stored)

    if found is None:
        return {
            "mode": "DRY_RUN",
            "action": "INSERT_CANDIDATE",
            "row_number": None,
            "serialized_row": serialized,
            "google_write_operations": [],
        }

    row_number, previous = found

    for field in IDENTITY_FIELDS:
        if previous[field] != requested[field]:
            raise ValueError(
                f"Immutable checkpoint identity mismatch: {field}"
            )

    if previous["previous_exported_version_id"] != (
        requested["previous_exported_version_id"]
    ):
        raise ValueError("Export baseline cannot change")

    if requested["attempts"] < previous["attempts"]:
        raise ValueError("Attempt count cannot decrease")

    if (
        previous["state"] == "COMPLETED"
        and requested["state"] != "COMPLETED"
    ):
        raise ValueError("Completed export cannot reopen")

    if (
        previous["verified_projection_digest"]
        and requested["verified_projection_digest"]
        != previous["verified_projection_digest"]
    ):
        raise ValueError("Verified digest cannot be replaced")

    if serialize_checkpoint(previous) == serialized:
        action = "NOOP"
    else:
        action = "UPDATE_CANDIDATE"

    return {
        "mode": "DRY_RUN",
        "action": action,
        "row_number": row_number,
        "serialized_row": serialized,
        "google_write_operations": [],
    }
