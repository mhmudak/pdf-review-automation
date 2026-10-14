"""Real Google Sheets checkpoint test ? STAGING ONLY."""

import argparse
import sys
from hashlib import sha256
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "src")
)

from sheets_adapter import SheetsAdapter
from v2_pm_checkpoint import (
    new_export_checkpoint,
    advance_checkpoint,
)
from v2_pm_checkpoint_adapter import (
    get_checkpoint,
    persist_checkpoint,
    read_checkpoint_table,
)

STAGING = "1X4NN9gnvQdXc65cPk9B-p2W-yiBlqZ2rcg8U-ujd2N4"
TEST_TAB = "V2 Integration Tests"


def main(apply):
    sheets = SheetsAdapter(STAGING)

    checkpoint = new_export_checkpoint(
        document_key="PROPS_STAGING_CHECKPOINT_TEST",
        version_id="staging-test-v1",
        pdf_sha256="a" * 64,
        output_spreadsheet_id=STAGING,
        output_tab=TEST_TAB,
    )

    export_id = checkpoint["export_id"]

    # Validate the existing table before doing anything.
    read_checkpoint_table(sheets)
    existing = get_checkpoint(sheets, export_id)

    print("=== V2 CHECKPOINT PERSISTENCE TEST ===")
    print("Destination: STAGING ONLY")
    print("Export ID:", export_id)
    print("Existing state:",
          existing["state"] if existing else "NONE")

    if not apply:
        print("DRY RUN: No writes performed")
        return

    if existing:
        if existing["state"] == "COMPLETED":
            print("NOOP: Checkpoint already completed")
            print("No duplicate checkpoint created")
            return

        raise RuntimeError(
            "An existing incomplete test checkpoint was found. "
            "Refusing to reset or overwrite its state."
        )

    # Persist PENDING before starting export work.
    result = persist_checkpoint(
        sheets, checkpoint, allow_writes=True
    )
    assert result["verified"] is True
    print("PASS: EXPORT_PENDING persisted")

    # Record the start and attempt number.
    checkpoint = advance_checkpoint(
        checkpoint, "START_EXPORT"
    )
    result = persist_checkpoint(
        sheets, checkpoint, allow_writes=True
    )
    assert result["verified"] is True
    print("PASS: EXPORTING persisted")
    print("Attempts:", checkpoint["attempts"])

    # Synthetic verification digest.
    # This test does NOT claim a PDF was exported.
    digest = sha256(
        b"PrOps staging synthetic checkpoint verification"
    ).hexdigest()

    checkpoint = advance_checkpoint(
        checkpoint,
        "EXPORT_VERIFIED",
        verification_digest=digest,
    )
    result = persist_checkpoint(
        sheets, checkpoint, allow_writes=True
    )
    assert result["verified"] is True
    print("PASS: EXPORT_VERIFIED persisted")

    # No emails are sent during this infrastructure test.
    checkpoint = advance_checkpoint(
        checkpoint, "COMPLETE_WITHOUT_NOTIFICATION"
    )
    result = persist_checkpoint(
        sheets, checkpoint, allow_writes=True
    )
    assert result["verified"] is True
    print("PASS: COMPLETED persisted")

    stored = get_checkpoint(sheets, export_id)

    assert stored is not None
    assert stored["state"] == "COMPLETED"
    assert stored["attempts"] == 1
    assert stored["verified_projection_digest"] == digest

    matching = [
        row for row in read_checkpoint_table(sheets)
        if row[0] == export_id
    ]
    assert len(matching) == 1

    print("SUCCESS: Persistent checkpoint verified")
    print("Exactly one matching checkpoint row")
    print("No PDF records changed")
    print("No emails sent")
    print("Production spreadsheets: UNCHANGED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply-staging", action="store_true"
    )
    args = parser.parse_args()
    main(args.apply_staging)
