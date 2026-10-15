"""Validate a real-dataset source change without writing data."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sheets_adapter import SheetsAdapter
from v2_output_projection import project_backend_rows
from v2_pm_combined_plan import plan_verified_pm_cells
from v2_pm_safe_writer import GuardedPMWriter, CellChange
from v2_pm_export_coordinator import (
    STAGING_ID, PM_TAB, INITIAL_BASELINE,
    read_source_snapshot, read_values, pad,
)

BACKEND_ID = "1DXZJsEG1993iEkzBNJWDAZYhFc2AC2Fm29DTjdYFWIg"
DOCUMENT = "IGCSE_ARABIC_2P"


def main():
    backend = SheetsAdapter(BACKEND_ID)
    staging = SheetsAdapter(STAGING_ID)

    raw = backend.get_all_values("_Entries_V2", refresh=True)
    headers = raw[0]

    records = [
        dict(zip(headers, pad(row, len(headers))))
        for row in raw[1:]
    ]
    records = [
        row for row in records
        if row.get("Document Key") == DOCUMENT
    ]

    current = project_backend_rows(records)["rows"]
    previous = read_source_snapshot(staging, INITIAL_BASELINE)
    pm_values = read_values(staging, PM_TAB, "V")

    target = next(
        row for row in current
        if not str(row.get("Reply Entry IDs") or "").strip()
    )

    root_id = str(target["Root Entry ID"])
    old_comment = str(target.get("Comment") or "")
    revised_comment = old_comment + " [SIMULATED SOURCE REVISION]"

    updated = [dict(row) for row in current]

    for row in updated:
        if str(row["Root Entry ID"]) == root_id:
            row["Comment"] = revised_comment
            break

    plan = plan_verified_pm_cells(
        pm_values, previous, updated
    )

    print("=== REAL-DATASET CHANGE VALIDATION ===")
    print("ROOTs:", len(current))
    print("Target ROOT:", root_id)
    print("Blockers:", len(plan["blockers"]))

    if plan["blockers"]:
        print("First blockers:", plan["blockers"][:5])
        raise RuntimeError("LEGITIMATE_SOURCE_CHANGE_BLOCKED")

    candidates = plan["cell_update_candidates"]
    print("Authorized cells:", [
        item.get("cell") for item in candidates
    ])

    if len(candidates) != 1:
        raise RuntimeError("EXPECTED_ONE_COMMENT_CHANGE")

    candidate = candidates[0]
    cell = str(candidate["cell"])

    if not cell.startswith("E"):
        raise RuntimeError("UNEXPECTED_TARGET_COLUMN")

    if candidate["root_entry_id"] != root_id:
        raise RuntimeError("ROOT_ID_MISMATCH")

    if candidate["new_value"] != revised_comment:
        raise RuntimeError("INCORRECT_NEW_COMMENT")

    print("PASS: Real-dataset change correctly planned")

    # Inspect the actual target without changing Google Sheets.
    change = CellChange(
        root_id=candidate["root_entry_id"],
        cell=cell,
        expected_value=candidate["expected_value"],
        new_value=candidate["new_value"],
    )

    writer = GuardedPMWriter(
        staging.service,
        STAGING_ID,
        PM_TAB,
        authorized_spreadsheet_id=STAGING_ID,
        authorized_tab=PM_TAB,
    )

    dry_result = writer.apply(
        [change], allow_writes=False
    )

    if dry_result["pending"] != [cell]:
        raise RuntimeError(
            "EXPECTED_ONE_PENDING_AUTHORIZED_WRITE"
        )

    print("PASS: Actual staging target verified before write")

    # Introduce a human edit in memory only.
    conflicted = [list(row) for row in pm_values]

    for position in range(1, len(conflicted)):
        row = pad(conflicted[position], 22)

        if row[14] == root_id:
            row[4] = "HUMAN EDIT - PROTECTED"
            conflicted[position] = row
            break
    else:
        raise RuntimeError("ROOT_MISSING_FROM_PM")

    conflict_plan = plan_verified_pm_cells(
        conflicted, previous, updated
    )

    if not conflict_plan["blockers"]:
        raise RuntimeError("HUMAN_EDIT_NOT_DETECTED")

    if conflict_plan["cell_update_candidates"]:
        raise RuntimeError(
            "UNSAFE_WRITE_CANDIDATES_WITH_CONFLICT"
        )

    print("PASS: Human-edit conflict blocks all writes")
    print("PASS: Existing ROOT identity protected")
    print("PASS: No other PM cell authorized")
    print("Google Sheets writes: 0")
    print("Production PM: UNCHANGED")


if __name__ == "__main__":
    main()
