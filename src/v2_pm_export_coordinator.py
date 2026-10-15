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
from v2_pm_staging_snapshot import new_root_row
from v2_pm_root_writer import (GuardedRootAppender, source_owned_root_matches)
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


def pm_grid_width(adapter, tab):
    """Read actual PM grid width; never guess that W exists."""
    response = adapter.service.spreadsheets().get(
        spreadsheetId=adapter.spreadsheet_id,
        fields="sheets(properties(title,gridProperties(columnCount)))",
    ).execute()
    matches = [
        item.get("properties", {}).get("gridProperties", {}).get("columnCount", 0)
        for item in response.get("sheets", [])
        if item.get("properties", {}).get("title") == tab
    ]
    if len(matches) != 1 or int(matches[0]) < 22:
        raise RuntimeError("PM_GRID_STRUCTURE_CONFLICT")
    return int(matches[0])


def pm_column_letter(position):
    """One-based spreadsheet column number to A1 notation."""
    result = ""
    while position:
        position, remainder = divmod(position - 1, 26)
        result = chr(65 + remainder) + result
    return result


def read_pm_grid(adapter, tab):
    """Read and validate managed headers and every PM custom column.

    Return only the canonical A:V view to the positional writer.
    A custom field after V is human-owned and never used for writes.
    """
    width = pm_grid_width(adapter, tab)
    full = read_values(adapter, tab, pm_column_letter(width))
    if not full or list(full[0][:22]) != list(PM_HEADER_SEQUENCE):
        raise RuntimeError("PM_OUTPUT_SCHEMA_CONFLICT")
    # Google Sheets omits empty trailing cells from returned rows.
    # Validate all physically existing columns, including blank W1.
    trailing = list(full[0][22:width])
    trailing.extend([""] * (width - 22 - len(trailing)))
    if any(not str(h).strip() for h in trailing):
        # Empty trailing headers are acceptable only when their cells
        # have no human content; a newly added, unused W is safe.
        for index, header in enumerate(trailing, start=22):
            if not str(header).strip() and any(
                len(row) > index and str(row[index]).strip()
                for row in full[1:]
            ):
                raise RuntimeError("UNNAMED_CUSTOM_COLUMN_WITH_DATA")
    if len([x for x in trailing if str(x).strip()]) != len(set(
        str(x).strip() for x in trailing if str(x).strip()
    )):
        raise RuntimeError("DUPLICATE_CUSTOM_COLUMN_HEADER")
    managed = set(PM_HEADER_SEQUENCE)
    if any(str(x).strip() in managed for x in trailing if str(x).strip()):
        raise RuntimeError("CUSTOM_COLUMN_HEADER_SHADOWS_SYSTEM")
    return [list(row[:22]) for row in full]


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
    latest = read_pm_grid(adapter, PM_TAB)
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


def prepare_new_root_insertions(
    pm_values, previous_projection, current_projection,
    backend_records,
):
    """Plan new ROOTs without modifying Google Sheets.

    Already-appended rows are verified for exact equality.
    Existing ROOTs remain in their original physical positions.
    """
    if not pm_values or pm_values[0] != PM_HEADER_SEQUENCE:
        raise RuntimeError("PM_OUTPUT_SCHEMA_CONFLICT")

    def index_projection(rows, label):
        indexed = {}
        for row in rows:
            key = clean(row.get("Root Entry ID")).strip()
            if not key or key in indexed:
                raise RuntimeError(label + "_ROOT_ID_CONFLICT")
            indexed[key] = row
        return indexed

    before = index_projection(previous_projection, "PREVIOUS")
    after = index_projection(current_projection, "CURRENT")

    # Removal of an existing source ROOT requires a separate,
    # human-reviewed policy; never silently remove PM rows.
    missing = set(before) - set(after)
    if missing:
        raise RuntimeError("SOURCE_ROOT_REMOVAL_REQUIRES_REVIEW")

    pm_rows = {}
    for raw in pm_values[1:]:
        row = pad(raw, 22)
        key = row[14].strip()
        if not key or key in pm_rows:
            raise RuntimeError("PM_ROOT_ID_CONFLICT")
        pm_rows[key] = row

    new_ids = set(after) - set(before)

    if set(pm_rows) - set(before) - new_ids:
        raise RuntimeError("UNEXPECTED_PM_ROOT_ID")

    if set(before) - set(pm_rows):
        raise RuntimeError("PREVIOUS_PM_ROOT_MISSING")

    backend_roots = {}
    for record in backend_records:
        if (
            clean(record.get("Relation Type")).strip().upper()
            == "ROOT"
            and clean(record.get("Active")).strip().upper()
            == "TRUE"
        ):
            entry_id = clean(record.get("Entry ID")).strip()
            if not entry_id or entry_id in backend_roots:
                raise RuntimeError("BACKEND_ROOT_ID_CONFLICT")
            backend_roots[entry_id] = record

    additions = []
    already_present = []

    # Use the current projection's deterministic reading order.
    for projected in current_projection:
        key = clean(projected["Root Entry ID"]).strip()
        if key not in new_ids:
            continue

        backend = backend_roots.get(key)
        if backend is None:
            raise RuntimeError("NEW_ROOT_BACKEND_RECORD_MISSING")

        row = new_root_row(projected, backend)

        if key in pm_rows:
            # Recovery after append: no second insertion.
            # A mismatching row is never overwritten.
            if not source_owned_root_matches(
                pm_rows[key], row
            ):
                raise RuntimeError("APPENDED_ROOT_CONTENT_CONFLICT")
            already_present.append(key)
        else:
            additions.append(row)

    # Only established ROOTs go through the existing-cell
    # delta planner. New ROOTs use the guarded appender.
    existing_pm_values = [
        list(pm_values[0]),
        *[
            pad(raw, 22)
            for raw in pm_values[1:]
            if pad(raw, 22)[14].strip() in before
        ],
    ]

    existing_current = [
        row for row in current_projection
        if clean(row.get("Root Entry ID")).strip() in before
    ]

    return {
        "existing_pm_values": existing_pm_values,
        "existing_current_projection": existing_current,
        "new_rows": additions,
        "already_present": already_present,
        "new_root_count": len(new_ids),
    }

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

    # A known, unchanged V2 version has already gone through
    # annotation/author-rule checks in execute_v2_pdf. Reuse
    # only the *latest* completed checkpoint: do not project,
    # read PM cells, or export identical content again.
    # Any pending, changed, or missing checkpoint falls through
    # to the full verified export and recovery logic.
    if v2_result.get("action") == "DUPLICATE_VERSION":
        checkpoint_adapter = SheetsAdapter(STAGING_ID)
        known_history = [
            deserialize_checkpoint(row)
            for row in read_checkpoint_table(checkpoint_adapter)
        ]
        known_history = [
            item for item in known_history
            if item["document_key"] == document
            and item["output_spreadsheet_id"] == STAGING_ID
            and item["output_tab"] == PM_TAB
        ]
        if known_history:
            latest_known = known_history[-1]
            if (
                latest_known["state"] == "COMPLETED"
                and latest_known["version_id"] == version
                and latest_known["pdf_sha256"] == sha
                and latest_known["verified_projection_digest"]
            ):
                return {
                    "verified": True,
                    "action": "ALREADY_EXPORTED",
                    "export_id": latest_known["export_id"],
                    "verified_projection_digest": (
                        latest_known["verified_projection_digest"]
                    ),
                    "reused_completed_checkpoint": True,
                }

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

    pm_values = read_pm_grid(staging, PM_TAB)
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

    root_plan = prepare_new_root_insertions(
        pm_values, previous, current, records
    )

    if source_table(previous) == source_table(current):
        count = verify_unchanged_pm(pm_values, current)
        print(f"V2 source unchanged: {count} PM ROOTs verified.")
        plan = {
            "blockers": [],
            "new_root_count": 0,
            "cell_update_candidates": [],
        }
    else:
        plan = plan_verified_pm_cells(
            root_plan["existing_pm_values"],
            previous,
            root_plan["existing_current_projection"],
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

        root_appender = GuardedRootAppender(
            staging.service, STAGING_ID, PM_TAB,
            authorized_spreadsheet_id=STAGING_ID,
            authorized_tab=PM_TAB,
        )

        for new_row in root_plan["new_rows"]:
            inserted = root_appender.apply(
                new_row, allow_writes=True
            )
            if not inserted["verified"]:
                raise RuntimeError("NEW_ROOT_INSERT_NOT_VERIFIED")

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


def validate_recovery_versions(pending, documents):
    """Reject recovery against the wrong backend PDF version."""
    indexed = {}

    for document in documents:
        key = clean(document.get("Document Key")).strip()
        if not key or key in indexed:
            raise RuntimeError("INVALID_BACKEND_DOCUMENT_REGISTRY")
        indexed[key] = document

    seen = set()

    for item in pending:
        document_key = item["document_key"]

        if document_key in seen:
            raise RuntimeError("MULTIPLE_PENDING_EXPORTS_FOR_DOCUMENT")
        seen.add(document_key)

        current = indexed.get(document_key)

        if current is None:
            raise RuntimeError(
                "PENDING_EXPORT_DOCUMENT_NOT_FOUND: " + document_key
            )

        if (
            clean(current.get("Current Version ID"))
            != item["version_id"]
            or clean(current.get("Current PDF SHA256"))
            != item["pdf_sha256"]
        ):
            raise RuntimeError(
                "PENDING_EXPORT_BACKEND_VERSION_CONFLICT: "
                + document_key
            )

    return len(pending)


def recover_pending_pm_exports(*, backend_sheets, config):
    """Resume unfinished staging exports before processing PDFs.

    Uses already persisted backend records. No PDF extraction.
    Never authorizes a production destination.
    """
    if (
        config.get("v2_pm_staging_apply") is not True
        or config.get("v2_pm_output_spreadsheet_id") != STAGING_ID
        or config.get("v2_pm_output_tab") != PM_TAB
    ):
        raise PermissionError("RECOVERY_STAGING_ONLY")

    if backend_sheets is None:
        raise RuntimeError("RECOVERY_BACKEND_REQUIRED")

    staging = SheetsAdapter(STAGING_ID)

    all_checkpoints = [
        deserialize_checkpoint(row)
        for row in read_checkpoint_table(staging)
    ]

    relevant = [
        checkpoint
        for checkpoint in all_checkpoints
        if (
            checkpoint["output_spreadsheet_id"] == STAGING_ID
            and checkpoint["output_tab"] == PM_TAB
            and checkpoint["state"] != "COMPLETED"
        )
    ]

    if not relevant:
        return {"recovered": 0, "pending": 0}

    # Delivery-uncertain and notification-pending states
    # require notification-specific reconciliation.
    # Never resend an email here.
    unsupported = [
        x for x in relevant
        if x["state"] not in (
            "EXPORT_PENDING",
            "EXPORTING",
            "EXPORT_VERIFIED",
        )
    ]
    if unsupported:
        raise RuntimeError(
            "NOTIFICATION_RECOVERY_REQUIRED: "
            + repr([x["export_id"] for x in unsupported])
        )

    values = backend_sheets.get_all_values(
        "_Documents", refresh=True
    )

    if not values:
        raise RuntimeError("BACKEND_DOCUMENTS_MISSING")

    headers = values[0]
    documents = [
        dict(zip(headers, pad(row, len(headers))))
        for row in values[1:]
    ]

    validate_recovery_versions(relevant, documents)

    # Recovery is idempotent: the coordinator recognizes
    # already-applied cells and existing checkpoints.
    results = []

    for checkpoint in relevant:
        result = export_verified_pm(
            backend_sheets=backend_sheets,
            output_sheets=None,
            v2_result={
                "document_key": checkpoint["document_key"],
                "version_id": checkpoint["version_id"],
                "sha256": checkpoint["pdf_sha256"],
            },
            drive_file=None,
            config=config,
        )

        if result.get("verified") is not True:
            raise RuntimeError(
                "PM_RECOVERY_NOT_VERIFIED: "
                + checkpoint["export_id"]
            )

        results.append(result)

    # Verify that recovery actually completed all scoped exports.
    remaining = [
        deserialize_checkpoint(row)
        for row in read_checkpoint_table(staging)
    ]

    still_pending = [
        x for x in remaining
        if (
            x["output_spreadsheet_id"] == STAGING_ID
            and x["output_tab"] == PM_TAB
            and x["state"] != "COMPLETED"
        )
    ]

    if still_pending:
        raise RuntimeError(
            "PM_RECOVERY_INCOMPLETE: "
            + repr([x["export_id"] for x in still_pending])
        )

    return {
        "recovered": len(results),
        "pending": 0,
    }
