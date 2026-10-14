"""PrOps V2: isolated Google Sheets cell-write integration test.

Only writes to the synthetic 'V2 Integration Tests' tab.
Never writes to backend or production PM spreadsheets.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "src")
)

from sheets_adapter import SheetsAdapter
from v2_pm_cell_plan import plan_pm_comment_cells
from v2_pm_reply_cell_plan import plan_pm_reply_cells

STAGING_ID = "1X4NN9gnvQdXc65cPk9B-p2W-yiBlqZ2rcg8U-ujd2N4"
TAB = "V2 Integration Tests"

ROOT1 = "props-stage-root-001"
ROOT2 = "props-stage-root-002"
REPLY1 = "props-stage-reply-001"
REPLY2 = "props-stage-reply-002"

NEW_COMMENT = "Review illustration caption and terminology."
NEW_REPLY = "Second reviewer ? Please verify the terminology."

ALLOWED_CELLS = {"E3", "G2", "V2"}


def read(adapter):
    response = (
        adapter.service.spreadsheets().values().get(
            spreadsheetId=STAGING_ID,
            range=f"'{TAB}'!A1:V3",
            valueRenderOption="FORMATTED_VALUE",
        ).execute()
    )
    values = response.get("values", [])

    if len(values) != 3:
        raise RuntimeError("Unexpected staging row count")

    return [
        list(row) + [""] * (22 - len(row))
        for row in values
    ]


def plan(values):
    if values[1][14] != ROOT1 or values[2][14] != ROOT2:
        raise RuntimeError("Synthetic ROOT ID mismatch")

    if values[1][8] != "Translation":
        raise RuntimeError("Manual category changed")

    comment = plan_pm_comment_cells(
        values,
        [{
            "root_entry_id": ROOT2,
            "field": "Comment",
            "expected_pm_value": "Review illustration caption.",
            "new_value": NEW_COMMENT,
            "reason": "VERIFIED_SOURCE_COMMENT_CHANGE",
        }],
    )

    reply = plan_pm_reply_cells(
        values,
        [{
            "Root Entry ID": ROOT1,
            "Reply Entry IDs": REPLY1,
            "Reply 1": "Sample Reviewer ? Initial reply",
        }],
        [{
            "root_entry_id": ROOT1,
            "reply_entry_id": REPLY2,
            "field": "Reply 2",
            "expected_pm_value": "",
            "new_value": NEW_REPLY,
            "reason": "VERIFIED_NEW_REPLY_ID",
        }],
    )

    if comment["conflicts"] or reply["conflicts"]:
        raise RuntimeError(
            f"Conflicts: {comment['conflicts']} "
            f"{reply['conflicts']}"
        )

    candidates = (
        comment["cell_update_candidates"]
        + reply["cell_update_candidates"]
    )

    if (
        len(set(item["cell"] for item in candidates))
        != len(candidates)
    ):
        raise RuntimeError("Duplicate target cells")

    if any(item["cell"] not in ALLOWED_CELLS
           for item in candidates):
        raise RuntimeError("Unauthorized staging cell")

    return candidates


def main(apply):
    adapter = SheetsAdapter(STAGING_ID)

    before = read(adapter)
    candidates = plan(before)

    print("=== REAL STAGING CELL TEST ===")
    print("Target:", TAB)
    print("Planned cells:", [x["cell"] for x in candidates])
    print("Changes required:", len(candidates))

    if not apply:
        print("DRY RUN: No writes performed")
        return

    if not candidates:
        print("NOOP: All changes already applied")
        return

    # Recheck target and all other cells immediately before writing.
    if read(adapter) != before:
        raise RuntimeError(
            "Staging changed before write; aborting"
        )

    service = adapter.service.spreadsheets().values()

    service.batchUpdate(
        spreadsheetId=STAGING_ID,
        body={
            "valueInputOption": "RAW",
            "data": [
                {
                    "range": f"'{TAB}'!{item['cell']}",
                    "values": [[item["new_value"]]],
                }
                for item in candidates
            ],
        },
    ).execute()

    after = read(adapter)

    # Check only the intended cells changed.
    target_positions = {
        "E3": (2, 4),
        "G2": (1, 6),
        "V2": (1, 21),
    }

    updated = {
        target_positions[item["cell"]]
        for item in candidates
    }

    for r in range(3):
        for c in range(22):
            if (r, c) not in updated:
                if before[r][c] != after[r][c]:
                    raise RuntimeError(
                        f"Unexpected modification: "
                        f"row={r+1}, col={c+1}"
                    )

    for item in candidates:
        r, c = target_positions[item["cell"]]
        if after[r][c] != item["new_value"]:
            raise RuntimeError(
                f"Read-back mismatch: {item['cell']}"
            )

    if plan(after):
        raise RuntimeError(
            "Idempotency failure: retry still plans writes"
        )

    print("SUCCESS: Updated cells verified")
    print("Manual category preserved")
    print("Existing reply preserved")
    print("Second execution would be NOOP")
    print("Production spreadsheet: UNCHANGED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply-staging",
        action="store_true",
    )
    args = parser.parse_args()
    main(args.apply_staging)
