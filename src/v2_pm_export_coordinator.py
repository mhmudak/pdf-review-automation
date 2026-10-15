"""Checkpointed V2 PM export coordinator.

STAGING ONLY in this implementation.
Real backend projection, verified source comparison,
guarded cell writes, immutable snapshots and checkpoints.

Production PM writes, new ROOT insertion and notifications
are deliberately not authorized.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sheets_adapter import SheetsAdapter
from v2_output_projection import project_backend_rows
from v2_pm_cell_plan import PM_HEADER_SEQUENCE
from v2_pm_combined_plan import plan_verified_pm_cells
from v2_pm_safe_writer import GuardedPMWriter, CellChange
from v2_pm_checkpoint import (
    new_export_checkpoint,
    advance_checkpoint,
)
from v2_pm_checkpoint_adapter import (
    get_checkpoint,
    persist_checkpoint,
    read_checkpoint_table,
)
from v2_pm_checkpoint_store import deserialize_checkpoint


STAGING_ID = "1X4NN9gnvQdXc65cPk9B-p2W-yiBlqZ2rcg8U-ujd2N4"
PM_TAB = "Trial PDF - All Data"
INITIAL_BASELINE = "_PM_Source_Baseline_V2"

SOURCE_HEADERS = [
    "Root Entry ID", "Comment", "Reply 1", "Reply 2",
    "Reply 3", "Reply Entry IDs", "Source Row Digest",
    "Snapshot ID",
]


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False,
        sort_keys=True, separators=(",", ":"),
    )


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def clean(value):
    return "" if value is None else str(value)


def ids(value):
    return " | ".join(
        part.strip()
        for part in clean(value).replace("|", ",").split(",")
        if part.strip()
    )


def pad(row, width):
    if len(row) > width:
        raise RuntimeError("Unexpected spreadsheet column count")
    return list(row) + [""] * (width - len(row))


def read_values(adapter, tab, end):
    return adapter.service.spreadsheets().values().get(
        spreadsheetId=adapter.spreadsheet_id,
        range=f"'{tab}'!A1:{end}",
        valueRenderOption="FORMATTED_VALUE",
    ).execute().get("values", [])


def source_fields(rows):
    result = {}
    for row in rows:
        key = clean(row.get("Root Entry ID")).strip()
        if not key or key in result:
            raise RuntimeError("Duplicate or missing source ROOT ID")

        if clean(row.get("Reply 4")).strip():
            raise RuntimeError("MORE_THAN_THREE_REPLIES")

        values = [
            key,
            clean(row.get("Comment")),
            clean(row.get("Reply 1")),
            clean(row.get("Reply 2")),
            clean(row.get("Reply 3")),
            ids(row.get("Reply Entry IDs")),
        ]
        result[key] = values

    return [result[k] for k in sorted(result)]


def source_table(rows):
    fields = source_fields(rows)
    snapshot_id = digest(fields)
    return [
        SOURCE_HEADERS,
        *[[*r, digest(r), snapshot_id] for r in fields],
    ]


def read_source_snapshot(adapter, tab):
    raw = read_values(adapter, tab, "H")
    if not raw or raw[0] != SOURCE_HEADERS:
        raise RuntimeError("SOURCE_SNAPSHOT_SCHEMA_CONFLICT")

    records = [pad(row, 8) for row in raw[1:]]
    if not records:
        raise RuntimeError("EMPTY_SOURCE_SNAPSHOT")

    previous_ids = set()
    snapshot_ids = set()

    for row in records:
        if not row[0] or row[0] in previous_ids:
            raise RuntimeError("SOURCE_SNAPSHOT_ID_CONFLICT")
        previous_ids.add(row[0])
        snapshot_ids.add(row[7])
        if digest(row[:6]) != row[6]:
            raise RuntimeError("SOURCE_SNAPSHOT_ROW_TAMPERED")

    if (
        len(snapshot_ids) != 1
        or digest([r[:6] for r in records])
        != next(iter(snapshot_ids))
    ):
        raise RuntimeError("SOURCE_SNAPSHOT_DIGEST_MISMATCH")

    return [
        dict(zip(SOURCE_HEADERS[:6], row[:6]))
        for row in records
    ]


def verify_full_pm_destination(adapter, expected_projection):
    """Verify complete PM source-owned state after export.

    Ignore human-owned categories and historical reply display
    differences, but never ignore ROOT IDs, source comments or
    ordered reply IDs.
    """
    latest = read_values(adapter, PM_TAB, "V")
    return verify_unchanged_pm(latest, expected_projection)


def snapshot_tab(export_id):
    return "_PM_Source_" + export_id[:20]


def persist_immutable_snapshot(adapter, tab, records):
    expected = source_table(records)
    service = adapter.service.spreadsheets()

    metadata = service.get(
        spreadsheetId=adapter.spreadsheet_id,
        fields="sheets(properties(title))",
    ).execute()

    exists = any(
        s["properties"]["title"] == tab
        for s in metadata.get("sheets", [])
    )

    if not exists:
        service.batchUpdate(
            spreadsheetId=adapter.spreadsheet_id,
            body={"requests": [{
                "addSheet": {
                    "properties": {
                        "title": tab,
                        "gridProperties": {
                            "rowCount": len(expected) + 10,
                            "columnCount": 8,
                            "frozenRowCount": 1,
                        },
                    },
                },
            }]},
        ).execute()

    existing = [
        pad(row, 8)
        for row in read_values(adapter, tab, "H")
    ]

    # Crash recovery is allowed only for an exact prefix.
    # Never overwrite different historical snapshot data.
    if existing != expected[:len(existing)]:
        raise RuntimeError("IMMUTABLE_SNAPSHOT_CONFLICT")

    if len(existing) < len(expected):
        start = len(existing) + 1
        remainder = expected[len(existing):]
        service.values().update(
            spreadsheetId=adapter.spreadsheet_id,
            range=f"'{tab}'!A{start}:H{len(expected)}",
            valueInputOption="RAW",
            body={"values": remainder},
        ).execute()

    actual = [
        pad(row, 8)
        for row in read_values(adapter, tab, "H")
    ]

    if actual != expected:
        raise RuntimeError("SNAPSHOT_READBACK_FAILED")

    return expected[1][7]


def checkpoint_save(adapter, checkpoint):
    response = persist_checkpoint(
        adapter, checkpoint, allow_writes=True
    )
    if not response["verified"]:
        raise RuntimeError("CHECKPOINT_READBACK_FAILED")
    return checkpoint



def verify_unchanged_pm(pm_values, source_rows):
    """Verify unchanged source against the actual PM destination.

    Historical reply display text is intentionally not overwritten:
    ROOT identity, source comment and reply IDs are checked.
    """
    if not pm_values or pm_values[0] != PM_HEADER_SEQUENCE:
        raise RuntimeError("PM_OUTPUT_SCHEMA_CONFLICT")

    expected = {}
    for row in source_rows:
        root = clean(row.get("Root Entry ID")).strip()
        if not root or root in expected:
            raise RuntimeError("SOURCE_ROOT_ID_CONFLICT")
        expected[root] = row

    actual = {}
    for raw in pm_values[1:]:
        row = pad(raw, 22)
        root = row[14].strip()
        if not root or root in actual:
            raise RuntimeError("PM_ROOT_ID_CONFLICT")
        actual[root] = row

    if set(actual) != set(expected):
        raise RuntimeError("PM_ROOT_SET_CONFLICT")

    for root, row in actual.items():
        projected = expected[root]

        if row[4] != clean(projected.get("Comment")):
            raise RuntimeError(
                "PM_COMMENT_CONFLICT: " + root
            )

        if ids(row[21]) != ids(
            projected.get("Reply Entry IDs")
        ):
            raise RuntimeError(
                "PM_REPLY_ID_CONFLICT: " + root
            )

    return len(expected)

def export_verified_pm(
    *,
    backend_sheets: Any,
    output_sheets: Any,
    v2_result: dict[str, Any],
    drive_file: Any,
    config: dict[str, Any],
):
    """Called by backend_router after backend synchronization.

    Fail closed unless explicitly enabled for staging.
    """

    if config.get("v2_pm_staging_apply") is not True:
        raise RuntimeError("V2_PM_STAGING_APPLY_NOT_AUTHORIZED")

    if (
        config.get("v2_pm_output_spreadsheet_id")
        != STAGING_ID
        or config.get("v2_pm_output_tab") != PM_TAB
    ):
        raise PermissionError("STAGING_DESTINATION_ONLY")

    if backend_sheets is None:
        raise RuntimeError("BACKEND_REQUIRED")

    document = clean(v2_result.get("document_key"))
    version = clean(v2_result.get("version_id"))
    sha = clean(v2_result.get("sha256"))

    if not document or not version or len(sha) != 64:
        raise RuntimeError("INVALID_V2_VERSION_IDENTITY")

    # The caller supplies a persisted V2 backend.
    values = backend_sheets.get_all_values(
        "_Entries_V2", refresh=True
    )
    if not values:
        raise RuntimeError("BACKEND_ENTRIES_MISSING")

    headers = values[0]
    records = [
        dict(zip(headers, pad(r, len(headers))))
        for r in values[1:]
    ]
    records = [
        r for r in records
        if r.get("Document Key") == document
    ]

    projection = project_backend_rows(records)
    current = projection["rows"]
    if not current:
        raise RuntimeError("EMPTY_V2_PROJECTION")

    staging = SheetsAdapter(STAGING_ID)

    pm_values = read_values(staging, PM_TAB, "V")
    if not pm_values or pm_values[0] != PM_HEADER_SEQUENCE:
        raise RuntimeError("PM_OUTPUT_SCHEMA_CONFLICT")

    # A checkpoint is durable across Cloud Run process restarts.
    history = [
        deserialize_checkpoint(row)
        for row in read_checkpoint_table(staging)
    ]
    history = [
        row for row in history
        if (
            row["document_key"] == document
            and row["output_spreadsheet_id"] == STAGING_ID
            and row["output_tab"] == PM_TAB
        )
    ]

    latest = history[-1] if history else None

    if latest and latest["state"] == "COMPLETED":
        if (
            latest["version_id"] == version
            and latest["pdf_sha256"] == sha
        ):
            prior = read_source_snapshot(
                staging, snapshot_tab(latest["export_id"])
            )
            if source_table(prior) != source_table(current):
                raise RuntimeError("COMPLETED_SOURCE_HAS_CHANGED")
            verify_unchanged_pm(pm_values, current)
            return {
                "verified": True,
                "action": "ALREADY_EXPORTED",
                "export_id": latest["export_id"],
            }

    if latest and latest["state"] != "COMPLETED":
        if (
            latest["version_id"] != version
            or latest["pdf_sha256"] != sha
        ):
            raise RuntimeError("PRIOR_EXPORT_RECOVERY_REQUIRED")
        checkpoint = latest
        previous_version = latest["previous_exported_version_id"]
        previous_checkpoint = next(
            (
                x for x in reversed(history)
                if (
                    x["version_id"] == previous_version
                    and x["state"] == "COMPLETED"
                )
            ),
            None,
        )
    else:
        previous_checkpoint = latest
        previous_version = (
            latest["version_id"] if latest else ""
        )
        checkpoint = new_export_checkpoint(
            document_key=document,
            version_id=version,
            pdf_sha256=sha,
            output_spreadsheet_id=STAGING_ID,
            output_tab=PM_TAB,
            previous_exported_version_id=previous_version,
        )

    previous_tab = (
        snapshot_tab(previous_checkpoint["export_id"])
        if previous_checkpoint else INITIAL_BASELINE
    )

    previous = read_source_snapshot(staging, previous_tab)

    if source_table(previous) == source_table(current):
        # Exact source identity: no source-derived changes.
        # Verify the destination independently before checkpointing.
        count = verify_unchanged_pm(pm_values, current)
        print(
            f"V2 source unchanged: {count} PM ROOTs verified."
        )
        plan = {
            "blockers": [],
            "new_root_count": 0,
            "cell_update_candidates": [],
        }
    else:
        # Actual version change: use the full, fail-closed
        # source/comment/reply planner.
        plan = plan_verified_pm_cells(
            pm_values, previous, current
        )

    if plan["blockers"] or plan["new_root_count"]:
        raise RuntimeError(
            "PM_EXPORT_REVIEW_REQUIRED: "
            + repr(plan["blockers"][:10])
        )

    changes = []
    for candidate in plan["cell_update_candidates"]:
        cell = clean(candidate["cell"])
        if not cell.startswith(("E", "F", "G", "H", "V")):
            raise RuntimeError("UNAUTHORIZED_CELL_COLUMN")

        changes.append(CellChange(
            root_id=candidate["root_entry_id"],
            cell=cell,
            expected_value=candidate["expected_value"],
            new_value=candidate["new_value"],
        ))

    writer = GuardedPMWriter(
        staging.service, STAGING_ID, PM_TAB,
        authorized_spreadsheet_id=STAGING_ID,
        authorized_tab=PM_TAB,
    )

    if checkpoint["state"] == "EXPORT_PENDING":
        checkpoint_save(staging, checkpoint)
        checkpoint = checkpoint_save(
            staging,
            advance_checkpoint(checkpoint, "START_EXPORT"),
        )

    elif checkpoint["state"] not in (
        "EXPORTING", "EXPORT_VERIFIED"
    ):
        raise RuntimeError("UNRECOVERABLE_CHECKPOINT_STATE")

    if checkpoint["state"] == "EXPORTING":
        result = writer.apply(changes, allow_writes=True)
        if not result["verified"]:
            raise RuntimeError("PM_CELL_WRITE_UNVERIFIED")

        # Never certify an export based only on changed cells.
        # Re-read and verify the entire PM source-owned state.
        verify_full_pm_destination(staging, current)

        # The new snapshot is immutable and read-back verified
        # BEFORE the export can be marked as verified.
        verified_digest = persist_immutable_snapshot(
            staging, snapshot_tab(checkpoint["export_id"]),
            current,
        )

        checkpoint = checkpoint_save(
            staging,
            advance_checkpoint(
                checkpoint, "EXPORT_VERIFIED",
                verification_digest=verified_digest,
            ),
        )

    if checkpoint["state"] == "EXPORT_VERIFIED":
        verified_digest = persist_immutable_snapshot(
            staging, snapshot_tab(checkpoint["export_id"]),
            current,
        )
        if verified_digest != checkpoint["verified_projection_digest"]:
            raise RuntimeError("VERIFIED_SNAPSHOT_DIGEST_CONFLICT")

        # Recheck the whole PM destination, including ROOT IDs
        # and reply IDs, before checkpoint completion.
        verify_full_pm_destination(staging, current)

        # Recheck authorized PM cell values before completion.
        for change in changes:
            if (
                writer.read_cell(change.cell) != change.new_value
            ):
                raise RuntimeError("PM_FINAL_READBACK_FAILED")

        checkpoint = checkpoint_save(
            staging,
            advance_checkpoint(
                checkpoint, "COMPLETE_WITHOUT_NOTIFICATION"
            ),
        )

    stored = get_checkpoint(staging, checkpoint["export_id"])
    if not stored or stored["state"] != "COMPLETED":
        raise RuntimeError("PM_EXPORT_NOT_COMPLETED")

    return {
        "verified": True,
        "action": "EXPORTED",
        "export_id": checkpoint["export_id"],
        "verified_projection_digest": (
            stored["verified_projection_digest"]
        ),
        "cell_changes": len(changes),
    }
