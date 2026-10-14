"""Staging-only verified PM comment export execution."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from sheets_adapter import SheetsAdapter
from v2_pm_safe_writer import GuardedPMWriter, CellChange
from v2_pm_export_preflight import main as preflight

STAGING = "1X4NN9gnvQdXc65cPk9B-p2W-yiBlqZ2rcg8U-ujd2N4"
TAB = "Trial PDF - All Data"


def prepare_changes(source_plan, comment_plan):
    blockers = []

    if source_plan["held_for_review"]:
        blockers.append("SOURCE_CONFLICT_OR_REPLY_CHANGE")

    if source_plan["new_root_candidates"]:
        blockers.append("NEW_ROOT_INSERTION_NOT_CONNECTED")

    if source_plan["historical_root_ids"]:
        blockers.append("HISTORICAL_ROOT_REQUIRES_REVIEW")

    if comment_plan["conflicts"]:
        blockers.append("COMMENT_CELL_CONFLICT")

    if blockers:
        raise RuntimeError(
            "EXPORT_BLOCKED: " + ", ".join(blockers)
        )

    changes = []

    for item in comment_plan["cell_update_candidates"]:
        if item.get("field") != "Comment":
            raise RuntimeError("Unexpected writable field")

        if not str(item["cell"]).startswith("E"):
            raise RuntimeError("Unexpected comment column")

        changes.append(
            CellChange(
                root_id=item["root_entry_id"],
                cell=item["cell"],
                expected_value=item["expected_value"],
                new_value=item["new_value"],
            )
        )

    return changes


def main(apply):
    comparison = preflight()

    changes = prepare_changes(
        comparison["source_plan"],
        comparison["comment_plan"],
    )

    print("\n=== GUARDED V2 STAGING EXPORT ===")
    print("Destination:", TAB)
    print("Authorized comment changes:", len(changes))

    adapter = SheetsAdapter(STAGING)

    writer = GuardedPMWriter(
        adapter.service,
        STAGING,
        TAB,
        authorized_spreadsheet_id=STAGING,
        authorized_tab=TAB,
    )

    # Explicitly inspect target cells using the guarded writer.
    result = writer.apply(
        changes,
        allow_writes=apply,
    )

    print("Pending cells:", result["pending"])
    print("Already applied:", result["already_applied"])
    print("Written cells:", result["written"])

    if not apply:
        print("DRY RUN ? no writes performed")
    elif result["verified"]:
        print("PASS: Guarded cell write/readback verified")
    else:
        raise RuntimeError("Export was not verified")

    # A successful cell update is NOT yet a completed PDF
    # export until its next durable baseline/checkpoint is
    # committed. Never send an email from this runner.
    print("Checkpoint completion: NOT ATTEMPTED")
    print("Notifications: DISABLED")
    print("Production PM spreadsheet: UNCHANGED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply-staging", action="store_true")
    args = parser.parse_args()
    main(args.apply_staging)
