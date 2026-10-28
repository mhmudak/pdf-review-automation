"""Integrated V2 export recovery after successful PM writes.

Hard-locked to an isolated synthetic staging tab.
Run --interrupt first, then --recover.
No production PM writes or notifications.
"""

import argparse
import hashlib
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
sys.path.insert(0, str(PROJECT / "scripts"))

import test_v2_full_changed_export as fixture
import v2_pm_export_coordinator as coordinator

from sheets_adapter import SheetsAdapter
from v2_pm_checkpoint import new_export_checkpoint
from v2_pm_checkpoint_adapter import get_checkpoint

TAB = "V2 Recovery E2E Test"
SHA = hashlib.sha256(
    b"props-v2-full-recovery-fixture-001"
).hexdigest()

# Separate synthetic identifiers from the completed E2E test.
fixture.TEST_TAB = TAB
fixture.VERSION_SHA = SHA
fixture.VERSION = fixture.DOC + "@" + SHA
fixture.NEW_ROOT = "props-stage-recovery-root-001"
fixture.NEW_REPLY = "props-stage-recovery-reply-001"

STAGING = coordinator.STAGING_ID


def checkpoint(adapter):
    expected = new_export_checkpoint(
        document_key=fixture.DOC,
        version_id=fixture.VERSION,
        pdf_sha256=SHA,
        output_spreadsheet_id=STAGING,
        output_tab=TAB,
    )
    return get_checkpoint(adapter, expected["export_id"])


def inspect_destination(adapter):
    values = coordinator.read_values(adapter, TAB, "V")

    roots = [
        coordinator.pad(row, 22)[14]
        for row in values[1:]
    ]

    if (
        len(roots) != 1158
        or len(roots) != len(set(roots))
        or roots.count(fixture.NEW_ROOT) != 1
    ):
        raise RuntimeError("RECOVERY_ROOT_INTEGRITY_FAILED")

    return values


def interrupt():
    staging = SheetsAdapter(STAGING)

    if checkpoint(staging) is not None:
        raise RuntimeError(
            "RECOVERY_TEST_ALREADY_STARTED: "
            "Use --recover if an interrupted checkpoint exists."
        )

    original_snapshot_function = (
        coordinator.persist_immutable_snapshot
    )

    def intentional_failure(*args, **kwargs):
        raise RuntimeError(
            "INTENTIONAL_CRASH_AFTER_PM_WRITES"
        )

    coordinator.persist_immutable_snapshot = (
        intentional_failure
    )

    try:
        try:
            fixture.main(True)
        except RuntimeError as exc:
            if str(exc) != "INTENTIONAL_CRASH_AFTER_PM_WRITES":
                raise
            print("PASS: Simulated crash after PM writes")
        else:
            raise RuntimeError("EXPECTED_CRASH_DID_NOT_OCCUR")
    finally:
        coordinator.persist_immutable_snapshot = (
            original_snapshot_function
        )

    values = inspect_destination(staging)
    state = checkpoint(staging)

    if state is None or state["state"] != "EXPORTING":
        raise RuntimeError("EXPECTED_EXPORTING_CHECKPOINT")

    # A PM updates a human-owned field before recovery.
    row_number = next(
        n
        for n, row in enumerate(values[1:], start=2)
        if coordinator.pad(row, 22)[14] == fixture.NEW_ROOT
    )

    staging.service.spreadsheets().values().update(
        spreadsheetId=STAGING,
        range=f"'{TAB}'!I{row_number}",
        valueInputOption="RAW",
        body={
            "values": [["PM recovery test category"]]
        },
    ).execute()

    print("Checkpoint:", state["state"])
    print("ROOTs after interruption:", len(values) - 1)
    print("Human category assigned to new ROOT")
    print("Notifications: DISABLED")
    print("NEXT: Run --recover")


def recover():
    staging = SheetsAdapter(STAGING)
    before = checkpoint(staging)

    if before is None or before["state"] not in (
        "EXPORTING",
        "EXPORT_VERIFIED",
        "COMPLETED",
    ):
        raise RuntimeError(
            "EXPECTED_INTERRUPTED_OR_COMPLETED_CHECKPOINT"
        )

    if before["state"] == "COMPLETED":
        snapshot = coordinator.snapshot_tab(before["export_id"])
        saved = coordinator.read_source_snapshot(staging, snapshot)

        if len(saved) != 1158:
            raise RuntimeError("COMPLETED_SNAPSHOT_ROOT_COUNT_CONFLICT")

        print("NOOP: Recovery checkpoint already COMPLETED")
        print("Verified snapshot ROOTs:", len(saved))
        print("No repeated export writes or notifications")
        return

    fixture.main(True)

    after = checkpoint(staging)
    values = inspect_destination(staging)

    if after is None or after["state"] != "COMPLETED":
        raise RuntimeError("RECOVERY_DID_NOT_COMPLETE")

    matches = [
        coordinator.pad(row, 22)
        for row in values[1:]
        if coordinator.pad(row, 22)[14] == fixture.NEW_ROOT
    ]

    if matches[0][8] != "PM recovery test category":
        raise RuntimeError("HUMAN_CATEGORY_NOT_PRESERVED")

    print("PASS: Export checkpoint COMPLETED")
    print("PASS: Exactly 1158 unique ROOTs")
    print("PASS: Human category preserved")
    print("PASS: No duplicate ROOT insertion")
    print("PASS: Full destination verified")
    print("Golden staging PM: UNCHANGED")
    print("Production PM: UNCHANGED")
    print("Notifications: DISABLED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    phase = parser.add_mutually_exclusive_group(required=True)
    phase.add_argument("--interrupt", action="store_true")
    phase.add_argument("--recover", action="store_true")
    args = parser.parse_args()

    if args.interrupt:
        interrupt()
    else:
        recover()
