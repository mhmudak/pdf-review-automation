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
import os
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
PRODUCTION_ID = "13f31vlPWQPWrt2auGukJA7oWrM-90Kp6yU8OhWT3ERE"
PM_TAB = "Trial PDF - All Data"
INITIAL_BASELINE = "_PM_Source_Baseline_V2"

SOURCE_HEADERS = [
    "Root Entry ID", "Comment", "Reply 1", "Reply 2",
    "Reply 3", "Reply Entry IDs", "Source Row Digest",
    "Snapshot ID",
]



def export_destination(config):
    """Explicit allowlist. Production requires separate config and runtime consent.

    Authorization is checked before creating a SheetsAdapter or accessing data.
    An empty environment value is NEVER equivalent to authorization.
    """
    destination = clean(config.get("v2_pm_output_spreadsheet_id")).strip()
    tab = clean(config.get("v2_pm_output_tab")).strip()
    if tab != PM_TAB:
        raise PermissionError("PM_TAB_NOT_AUTHORIZED")
    if destination == STAGING_ID:
        if config.get("v2_pm_staging_apply") is not True:
            raise PermissionError("V2_PM_STAGING_APPLY_NOT_AUTHORIZED")
    elif destination == PRODUCTION_ID:
        if config.get("v2_pm_production_apply") is not True or os.environ.get(
            "V2_PM_PRODUCTION_AUTHORIZED", ""
        ) != "YES_I_AUTHORIZE_PRODUCTION_PM_WRITES":
            raise PermissionError("PRODUCTION_PM_EXPLICIT_APPROVAL_REQUIRED")
        if os.environ.get("NOTIFICATIONS_ENABLED", "").lower() in (
            "true", "1", "yes", "on",
        ):
            raise PermissionError("PRODUCTION_PM_NOTIFICATIONS_REQUIRE_SEPARATE_RELEASE")
    else:
        raise PermissionError("PM_DESTINATION_NOT_ALLOWLISTED")
    return destination


def require_destination_bootstrap(adapter, destination):
    """Production must have a complete, digest-verified source baseline.

    Never bootstrap or modify production baseline implicitly. A separate,
    reviewed baseline provisioning procedure is needed first.
    """
    if destination == PRODUCTION_ID:
        read_source_snapshot(adapter, INITIAL_BASELINE)
        read_checkpoint_table(adapter)


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
    """Read physical PM grid and return canonical A:V projection.

    The physical mapping is validated from unique header names; unknown
    columns are PM-owned and never included in source-owned writes.
    """
    width = pm_grid_width(adapter, tab)
    full = read_values(adapter, tab, pm_column_letter(width))
    from v2_pm_column_mapping import PMColumnMapping
    mapping = PMColumnMapping.from_rows(full, width)
    return mapping.canonical_rows(full)


def read_pm_mapping(adapter, tab):
    from v2_pm_column_mapping import PMColumnMapping
    width = pm_grid_width(adapter, tab)
    full = read_values(adapter, tab, pm_column_letter(width))
    return PMColumnMapping.from_rows(full, width)


def read_values(adapter, tab, end):
    return adapter.service.spreadsheets().values().get(
        spreadsheetId=adapter.spreadsheet_id,
        range=f"'{tab}'!A1:{end}",
        valueRenderOption="FORMATTED_VALUE",
    ).execute().get("values", [])


def source_fields(rows):
    """Canonical source fields; legacy Reply 1–3 order is preserved."""
    from v2_pm_dynamic_source_snapshot import create_table
    return [row[:-2] for row in create_table(rows)[1:]]


def source_table(rows):
    from v2_pm_dynamic_source_snapshot import create_table
    return create_table(rows)


def read_source_snapshot(adapter, tab):
    """Read legacy or dynamic snapshots, verifying the entire digest."""
    from v2_pm_dynamic_source_snapshot import read_table, validate_headers
    # Read the whole header by querying a bounded range, not just A:H.
    header_response = adapter.service.spreadsheets().values().get(
        spreadsheetId=adapter.spreadsheet_id,
        range=f"'{tab}'!A1:ZZ1",
        valueRenderOption="FORMATTED_VALUE",
    ).execute()
    headers = header_response.get("values", [])
    if not headers:
        raise RuntimeError("EMPTY_SOURCE_SNAPSHOT")
    validate_headers(headers[0])
    width = len(headers[0])
    return read_table(read_values(adapter, tab, pm_column_letter(width)))


def verify_full_pm_destination(adapter, expected_projection, *, previous_projection=None):
    """Verify source-owned cells and, when needed, physical Reply 4+.

    The canonical A:V verification preserves historical compatibility.
    Extended replies MUST be checked against freshly read physical columns;
    they cannot be proven correct from the truncated canonical grid.
    """
    latest = read_pm_grid(adapter, PM_TAB)
    count = verify_unchanged_pm(latest, expected_projection)

    from v2_pm_dynamic_reply_columns import reply_depth
    if reply_depth(expected_projection) > 3:
        if previous_projection is None:
            raise RuntimeError("DYNAMIC_REPLY_BASELINE_REQUIRED")
        from v2_pm_dynamic_readback import verify_dynamic_reply_readback
        width = pm_grid_width(adapter, PM_TAB)
        physical = read_values(adapter, PM_TAB, pm_column_letter(width))
        from v2_pm_column_mapping import PMColumnMapping
        PMColumnMapping.from_rows(physical, width)
        verify_dynamic_reply_readback(
            physical, expected_projection,
            previous_projection=previous_projection,
        )
    return count


def snapshot_tab(export_id):
    return "_PM_Source_" + export_id[:20]


def persist_immutable_snapshot(adapter, tab, records):
    """Write and verify immutable legacy or dynamic source snapshots.

    Existing snapshots are never resized or overwritten on mismatch.
    Recovery writes are permitted only for an identical row prefix.
    """
    expected = source_table(records)
    width = len(expected[0])
    end_col = pm_column_letter(width)
    service = adapter.service.spreadsheets()
    metadata = service.get(
        spreadsheetId=adapter.spreadsheet_id,
        fields="sheets(properties(title))",
    ).execute()
    exists = any(s["properties"]["title"] == tab for s in metadata.get("sheets", []))
    if not exists:
        service.batchUpdate(
            spreadsheetId=adapter.spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {
                "title": tab,
                "gridProperties": {
                    "rowCount": len(expected) + 10,
                    "columnCount": width,
                    "frozenRowCount": 1,
                },
            }}}]},
        ).execute()
    existing = [pad(row, width) for row in read_values(adapter, tab, end_col)]
    if existing != expected[:len(existing)]:
        raise RuntimeError("IMMUTABLE_SNAPSHOT_CONFLICT")
    if len(existing) < len(expected):
        first = len(existing) + 1
        service.values().update(
            spreadsheetId=adapter.spreadsheet_id,
            range=f"'{tab}'!A{first}:{end_col}{len(expected)}",
            valueInputOption="RAW",
            body={"values": expected[len(existing):]},
        ).execute()
    actual = [pad(row, width) for row in read_values(adapter, tab, end_col)]
    if actual != expected:
        raise RuntimeError("SNAPSHOT_READBACK_FAILED")
    return expected[1][-1]


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

def legacy_source_for_dynamic_planner(previous, current):
    """Use legacy delta only for comment changes; replies have a separate ID-aware planner."""
    prior = {clean(r.get("Root Entry ID")): r for r in previous}
    result = []
    for row in current:
        old = prior.get(clean(row.get("Root Entry ID")))
        item = dict(row)
        if old is not None:
            for name in set(old) | set(row):
                if name == "Reply Entry IDs" or (
                    name.startswith("Reply ") and name[6:].isdigit()
                ):
                    item[name] = old.get(name, "")
        result.append(item)
    return result


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

    destination = export_destination(config)

    if backend_sheets is None:
        raise RuntimeError("BACKEND_REQUIRED")

    document = clean(v2_result.get("document_key"))
    version = clean(v2_result.get("version_id"))
    sha = clean(v2_result.get("sha256"))

    if not document or not version or len(sha) != 64:
        raise RuntimeError("INVALID_V2_VERSION_IDENTITY")

    output_adapter = SheetsAdapter(destination)
    require_destination_bootstrap(output_adapter, destination)

    # A known, unchanged V2 version has already gone through
    # annotation/author-rule checks in execute_v2_pdf. Reuse
    # only the *latest* completed checkpoint: do not project,
    # read PM cells, or export identical content again.
    # Any pending, changed, or missing checkpoint falls through
    # to the full verified export and recovery logic.
    if v2_result.get("action") == "DUPLICATE_VERSION":
        checkpoint_adapter = output_adapter
        known_history = [
            deserialize_checkpoint(row)
            for row in read_checkpoint_table(checkpoint_adapter)
        ]
        known_history = [
            item for item in known_history
            if item["document_key"] == document
            and item["output_spreadsheet_id"] == destination
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

    staging = output_adapter

    pm_values = read_pm_grid(staging, PM_TAB)
    pm_mapping = read_pm_mapping(staging, PM_TAB)
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
            and row["output_spreadsheet_id"] == destination
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
            output_spreadsheet_id=destination,
            output_tab=PM_TAB,
            previous_exported_version_id=previous_version,
        )

    previous_tab = (
        snapshot_tab(previous_checkpoint["export_id"])
        if previous_checkpoint else INITIAL_BASELINE
    )

    previous = read_source_snapshot(staging, previous_tab)

    from v2_pm_dynamic_reply_columns import reply_depth, plan_reply_column_expansion
    from v2_pm_reply_delta import reply_ids
    dynamic = reply_depth(current) > 3
    if dynamic:
        previous_roots = {clean(r.get("Root Entry ID")) for r in previous}
        if any(
            clean(r.get("Root Entry ID")) not in previous_roots
            and len(reply_ids(r)) > 3 for r in current
        ):
            raise RuntimeError("DYNAMIC_NEW_ROOT_REQUIRES_REVIEW")
        width = pm_grid_width(staging, PM_TAB)
        physical = read_values(staging, PM_TAB, pm_column_letter(width))
        column_plan = plan_reply_column_expansion(physical, width, current)
    else:
        column_plan = None

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
            (legacy_source_for_dynamic_planner(
                previous, root_plan["existing_current_projection"]
            ) if dynamic else root_plan["existing_current_projection"]),
            approved_author_aliases=config.get("reviewer_aliases", {}),
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
            cell=pm_mapping.physical_cell(cell),
            expected_value=candidate["expected_value"],
            new_value=candidate["new_value"],
        ))

    writer = GuardedPMWriter(
        staging.service, destination, PM_TAB,
        authorized_spreadsheet_id=destination,
        authorized_tab=PM_TAB,
        column_mapping=pm_mapping,
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
        if dynamic:
            from v2_pm_dynamic_column_writer import DynamicReplyColumnWriter
            from v2_pm_dynamic_reply_writer import apply_dynamic_reply_plan
            columns = DynamicReplyColumnWriter(
                staging.service, destination, PM_TAB,
                authorized_spreadsheet_id=destination,
                authorized_tab=PM_TAB,
            )
            # Explicit staging-only opt-in. The column writer independently
            # verifies every cell of each trailing blank column before reuse.
            reuse_verified_blank = (
                destination == STAGING_ID
                and config.get("v2_pm_reuse_verified_blank_columns") is True
            )
            expanded = columns.apply(
                current,
                allow_writes=True,
                reuse_trailing_blank=reuse_verified_blank,
            )
            if not expanded["verified"]:
                raise RuntimeError("PM_DYNAMIC_HEADERS_UNVERIFIED")
            # Rebind every staged legacy edit to freshly resolved physical
            # positions; J onward moved right when replies were inserted.
            pm_mapping = read_pm_mapping(staging, PM_TAB)
            changes = [CellChange(
                root_id=item["root_entry_id"],
                cell=pm_mapping.physical_cell(clean(item["cell"])),
                expected_value=item["expected_value"],
                new_value=item["new_value"],
            ) for item in plan["cell_update_candidates"]]
            writer = GuardedPMWriter(
                staging.service, destination, PM_TAB,
                authorized_spreadsheet_id=destination,
                authorized_tab=PM_TAB,
                column_mapping=pm_mapping,
            )
            width = pm_grid_width(staging, PM_TAB)
            physical = read_values(staging, PM_TAB, pm_column_letter(width))
            updated = apply_dynamic_reply_plan(
                staging.service, destination, PM_TAB,
                authorized_spreadsheet_id=destination,
                authorized_tab=PM_TAB,
                sheet_values=physical, grid_width=width,
                previous_projection=previous,
                current_projection=current,
                approved_author_aliases=config.get("reviewer_aliases", {}),
                allow_writes=True,
            )
            if not updated["verified"]:
                raise RuntimeError("PM_DYNAMIC_REPLY_WRITE_UNVERIFIED")
        result = writer.apply(changes, allow_writes=True)
        if not result["verified"]:
            raise RuntimeError("PM_CELL_WRITE_UNVERIFIED")

        root_appender = GuardedRootAppender(
            staging.service, destination, PM_TAB,
            authorized_spreadsheet_id=destination,
            authorized_tab=PM_TAB,
            column_mapping=pm_mapping,
        )

        for new_row in root_plan["new_rows"]:
            inserted = root_appender.apply(
                new_row, allow_writes=True
            )
            if not inserted["verified"]:
                raise RuntimeError("NEW_ROOT_INSERT_NOT_VERIFIED")

        # Never certify an export based only on changed cells.
        # Re-read and verify the entire PM source-owned state.
        verify_full_pm_destination(
            staging, current, previous_projection=previous,
        )

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
        verify_full_pm_destination(
            staging, current, previous_projection=previous,
        )

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
    destination = export_destination(config)

    if backend_sheets is None:
        raise RuntimeError("RECOVERY_BACKEND_REQUIRED")

    staging = SheetsAdapter(destination)
    require_destination_bootstrap(staging, destination)

    all_checkpoints = [
        deserialize_checkpoint(row)
        for row in read_checkpoint_table(staging)
    ]

    relevant = [
        checkpoint
        for checkpoint in all_checkpoints
        if (
            checkpoint["output_spreadsheet_id"] == destination
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
            x["output_spreadsheet_id"] == destination
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
