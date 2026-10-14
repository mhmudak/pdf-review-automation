"""PrOps V2: changed-source export and interruption recovery.

Writes only synthetic E3 and checkpoint table in STAGING.
Uses a deterministic test-source revision, not an uploaded PDF.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "src")
)

from sheets_adapter import SheetsAdapter
from v2_pm_source_delta import plan_verified_source_delta
from v2_pm_cell_plan import plan_pm_comment_cells
from v2_pm_safe_writer import GuardedPMWriter, CellChange
from v2_pm_checkpoint import new_export_checkpoint, advance_checkpoint
from v2_pm_checkpoint_adapter import get_checkpoint, persist_checkpoint

STAGING = "1X4NN9gnvQdXc65cPk9B-p2W-yiBlqZ2rcg8U-ujd2N4"
TAB = "V2 Integration Tests"
ROOT = "props-stage-root-002"
CELL = "E3"

OLD = "Review illustration caption and terminology."
NEW = "Review illustration caption and terminology ? verified revision."

DOCUMENT = "PROPS_STAGING_CHANGED_SOURCE_TEST"
VERSION = "staging-changed-comment-v1"
TEST_SHA = hashlib.sha256(
    b"PrOps synthetic changed-source fixture v1"
).hexdigest()


def digest(record):
    return hashlib.sha256(
        json.dumps(
            record,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def get_pm_values(adapter):
    data = adapter.service.spreadsheets().values().get(
        spreadsheetId=STAGING,
        range=f"'{TAB}'!A1:V3",
        valueRenderOption="FORMATTED_VALUE",
    ).execute().get("values", [])

    if len(data) != 3:
        raise RuntimeError("Unexpected staging test row count")

    return [
        list(row) + [""] * (22 - len(row))
        for row in data
    ]


def persist(adapter, checkpoint):
    result = persist_checkpoint(
        adapter, checkpoint, allow_writes=True
    )
    if not result["verified"]:
        raise RuntimeError("Checkpoint persistence not verified")
    return checkpoint


def main(apply, interrupt):
    adapter = SheetsAdapter(STAGING)
    writer = GuardedPMWriter(
        adapter.service,
        STAGING,
        TAB,
        authorized_spreadsheet_id=STAGING,
        authorized_tab=TAB,
    )

    expected_checkpoint = new_export_checkpoint(
        document_key=DOCUMENT,
        version_id=VERSION,
        pdf_sha256=TEST_SHA,
        output_spreadsheet_id=STAGING,
        output_tab=TAB,
    )

    export_id = expected_checkpoint["export_id"]
    existing = get_checkpoint(adapter, export_id)

    values = get_pm_values(adapter)
    current_comment = values[2][4]

    if values[2][14] != ROOT:
        raise RuntimeError("ROOT identity changed")

    if current_comment not in (OLD, NEW):
        raise RuntimeError(
            "MANUAL_EDIT_CONFLICT: Unexpected E3 content"
        )

    if existing and any(
        existing[k] != expected_checkpoint[k]
        for k in (
            "document_key", "version_id", "pdf_sha256",
            "output_spreadsheet_id", "output_tab",
        )
    ):
        raise RuntimeError("Checkpoint identity mismatch")

    if existing and existing["state"] == "COMPLETED":
        if current_comment != NEW:
            raise RuntimeError(
                "Completed export destination was modified"
            )
        print("NOOP: Verified export already completed")
        return

    if existing and existing["state"] not in (
        "EXPORT_PENDING", "EXPORTING", "EXPORT_VERIFIED"
    ):
        raise RuntimeError(
            f"Unexpected checkpoint state: {existing['state']}"
        )

    previous = [{
        "Root Entry ID": ROOT,
        "Comment": OLD,
    }]
    updated = [{
        "Root Entry ID": ROOT,
        "Comment": NEW,
    }]

    # Check source-change authorization against the existing PM
    # value on the first pass. During recovery, an already-written
    # NEW value is permitted only when its checkpoint exists.
    if current_comment == OLD:
        source_plan = plan_verified_source_delta(
            [{"Root Entry ID": ROOT, "Comment": current_comment}],
            previous,
            updated,
        )
        if (
            source_plan["held_for_review"]
            or len(source_plan["verified_cell_update_candidates"]) != 1
        ):
            raise RuntimeError("Source change was not verified")

        cell_plan = plan_pm_comment_cells(
            values,
            source_plan["verified_cell_update_candidates"],
        )
        if (
            cell_plan["conflicts"]
            or len(cell_plan["cell_update_candidates"]) != 1
            or cell_plan["cell_update_candidates"][0]["cell"] != CELL
        ):
            raise RuntimeError("Unsafe comment cell plan")
    elif existing is None:
        raise RuntimeError(
            "New value exists without export checkpoint"
        )

    change = CellChange(
        root_id=ROOT,
        cell=CELL,
        expected_value=OLD,
        new_value=NEW,
    )

    print("=== V2 CHANGED-SOURCE RECOVERY TEST ===")
    print("Destination: STAGING synthetic E3 only")
    print("Existing checkpoint:",
          existing["state"] if existing else "NONE")
    print("Current comment:", current_comment)
    print("New source comment:", NEW)

    if not apply:
        preview = writer.apply([change], allow_writes=False)
        print("Pending cells:", preview["pending"])
        print("Already applied:", preview["already_applied"])
        print("DRY RUN ? no writes")
        return

    checkpoint = existing or persist(
        adapter, expected_checkpoint
    )

    if checkpoint["state"] == "EXPORT_PENDING":
        checkpoint = persist(
            adapter,
            advance_checkpoint(checkpoint, "START_EXPORT"),
        )

    if interrupt:
        if checkpoint["state"] != "EXPORTING":
            raise RuntimeError("Cannot interrupt this state")
        print("SIMULATED INTERRUPTION: checkpoint is EXPORTING")
        print("No PM cell write attempted")
        return

    if checkpoint["state"] == "EXPORTING":
        result = writer.apply([change], allow_writes=True)
        if not result["verified"]:
            raise RuntimeError("Destination write not verified")

        print("Written:", result["written"])
        print("Already applied:", result["already_applied"])

        if writer.read_cell(CELL) != NEW:
            raise RuntimeError("Comment read-back failed")
        if writer.read_cell("O3") != ROOT:
            raise RuntimeError("ROOT read-back failed")

        verification_digest = digest({
            "document": DOCUMENT,
            "version": VERSION,
            "root_id": ROOT,
            "comment": writer.read_cell(CELL),
        })

        checkpoint = persist(
            adapter,
            advance_checkpoint(
                checkpoint,
                "EXPORT_VERIFIED",
                verification_digest=verification_digest,
            ),
        )

    if checkpoint["state"] == "EXPORT_VERIFIED":
        if writer.read_cell(CELL) != NEW:
            raise RuntimeError("Export no longer matches destination")
        checkpoint = persist(
            adapter,
            advance_checkpoint(
                checkpoint, "COMPLETE_WITHOUT_NOTIFICATION"
            ),
        )

    final = get_checkpoint(adapter, export_id)

    if not final or final["state"] != "COMPLETED":
        raise RuntimeError("Checkpoint completion failed")

    print("SUCCESS: Changed comment verified")
    print("SUCCESS: Durable checkpoint COMPLETED")
    print("Attempts:", final["attempts"])
    print("Notifications: DISABLED")
    print("Production PM: UNCHANGED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply-staging", action="store_true")
    parser.add_argument(
        "--interrupt-after-start", action="store_true"
    )
    args = parser.parse_args()

    if args.interrupt_after_start and not args.apply_staging:
        parser.error(
            "--interrupt-after-start requires --apply-staging"
        )

    main(args.apply_staging, args.interrupt_after_start)
