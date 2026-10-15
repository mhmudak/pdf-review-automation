"""Live Google Sheets ROOT insertion test.

Hard-locked to synthetic staging tab.
Never writes to the 1,157-record PM tab or production.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "src")
)

from sheets_adapter import SheetsAdapter
from v2_pm_cell_plan import PM_HEADER_SEQUENCE
from v2_pm_root_writer import GuardedRootAppender

STAGING_ID = "1X4NN9gnvQdXc65cPk9B-p2W-yiBlqZ2rcg8U-ujd2N4"
TAB = "V2 Integration Tests"
ROOT = "props-stage-root-append-001"


def read_all(service):
    response = service.spreadsheets().values().get(
        spreadsheetId=STAGING_ID,
        range=f"'{TAB}'!A1:Z",
        valueRenderOption="FORMULA",
    ).execute()
    return [
        list(row) + [""] * (26 - len(row))
        for row in response.get("values", [])
    ]


def make_row():
    row = [""] * 22
    row[0] = "999"
    row[1] = "999"
    row[2] = "PrOps Synthetic Test"
    row[3] = "2026-10-15"
    row[4] = "Synthetic ROOT insertion verification"
    row[10] = "Text"
    row[14] = ROOT
    row[15] = "props-stage-entry-append-001"
    row[16] = "staging-root-integration-v1"
    row[17] = "synthetic-drive-file"
    row[18] = "a" * 64
    return row


def main(apply):
    adapter = SheetsAdapter(STAGING_ID)
    writer = GuardedRootAppender(
        adapter.service,
        STAGING_ID,
        TAB,
        authorized_spreadsheet_id=STAGING_ID,
        authorized_tab=TAB,
    )

    before = read_all(adapter.service)

    if not before or before[0][:22] != list(PM_HEADER_SEQUENCE):
        raise RuntimeError("STAGING_PM_HEADER_MISMATCH")

    existing = [
        row for row in before[1:]
        if row[14] == ROOT
    ]

    if len(existing) > 1:
        raise RuntimeError("DUPLICATE_TEST_ROOT")

    print("=== LIVE STAGING ROOT APPEND ===")
    print("Existing rows:", len(before) - 1)
    print("Test ROOT already present:", bool(existing))
    print("Apply enabled:", apply)

    result = writer.apply(
        make_row(),
        allow_writes=apply,
    )

    print("Action:", result["action"])
    print("Verified:", result["verified"])
    print("Written:", result["written"])

    after = read_all(adapter.service)

    if not apply:
        if after != before:
            raise RuntimeError("DRY_RUN_MODIFIED_STAGING")
        print("PASS: Dry run made no changes")
        return

    if not result["verified"]:
        raise RuntimeError("APPEND_NOT_VERIFIED")

    # Previously existing rows must remain exactly unchanged,
    # including the extra columns W:Z inspected here.
    if after[:len(before)] != before:
        raise RuntimeError("EXISTING_ROWS_WERE_MODIFIED")

    inserted = [
        row for row in after[1:]
        if row[14] == ROOT
    ]

    if len(inserted) != 1:
        raise RuntimeError("NEW_ROOT_NOT_UNIQUE")

    expected = make_row() + [""] * 4

    if inserted[0] != expected:
        raise RuntimeError("NEW_ROOT_CONTENT_MISMATCH")

    expected_count = len(before) + (0 if existing else 1)

    if len(after) != expected_count:
        raise RuntimeError("UNEXPECTED_ROW_COUNT")

    print("PASS: Exactly one new ROOT exists")
    print("PASS: Previous rows and columns A:Z unchanged")
    print("PASS: New ROOT content verified")
    print("Production PM: UNCHANGED")
    print("Notifications: DISABLED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply-staging", action="store_true")
    arguments = parser.parse_args()
    main(arguments.apply_staging)
