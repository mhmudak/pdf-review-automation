"""Verified comment and reply export ? staging only.

Uses durable source baseline and existing guarded writer.
Does not commit checkpoints, advance baselines, or send emails.
"""

import argparse
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
sys.path.insert(0, str(PROJECT / "scripts"))

from sheets_adapter import SheetsAdapter
from v2_pm_combined_plan import plan_verified_pm_cells
from v2_pm_safe_writer import GuardedPMWriter, CellChange
from v2_pm_export_preflight import main as preflight

STAGING = "1X4NN9gnvQdXc65cPk9B-p2W-yiBlqZ2rcg8U-ujd2N4"
TAB = "Trial PDF - All Data"


def convert_candidates(plan):
    """Reject unsupported fields before any write."""
    if plan["blockers"]:
        raise RuntimeError(
            "PM_EXPORT_BLOCKED: " + repr(plan["blockers"][:10])
        )

    if plan["new_root_count"]:
        raise RuntimeError("NEW_ROOT_INSERTION_NOT_CONNECTED")

    result = []
    seen = set()

    for item in plan["cell_update_candidates"]:
        cell = str(item["cell"])
        field = str(item["field"])

        if cell in seen:
            raise RuntimeError("Duplicate target cell")
        seen.add(cell)

        allowed = (
            (field == "Comment" and cell.startswith("E"))
            or (
                field in ("Reply 1", "Reply 2", "Reply 3")
                and cell.startswith({
                    "Reply 1": "F",
                    "Reply 2": "G",
                    "Reply 3": "H",
                }[field])
            )
            or (
                field == "Reply Entry IDs"
                and cell.startswith("V")
            )
        )

        if not allowed:
            raise RuntimeError(
                f"Unexpected candidate field/cell: {field}/{cell}"
            )

        result.append(
            CellChange(
                root_id=item["root_entry_id"],
                cell=cell,
                expected_value=item["expected_value"],
                new_value=item["new_value"],
            )
        )

    return result


def main(apply):
    comparison = preflight()

    plan = plan_verified_pm_cells(
        comparison["pm_values"],
        comparison["previous_projection"],
        comparison["current_projection"],
    )

    changes = convert_candidates(plan)

    print("\n=== COMBINED V2 STAGING EXPORT ===")
    print("Destination: STAGING ONLY")
    print("Authorized cells:", [x.cell for x in changes])
    print("Already applied:", plan["already_applied"])
    print("Blockers:", len(plan["blockers"]))

    adapter = SheetsAdapter(STAGING)

    writer = GuardedPMWriter(
        adapter.service,
        STAGING,
        TAB,
        authorized_spreadsheet_id=STAGING,
        authorized_tab=TAB,
    )

    result = writer.apply(
        changes,
        allow_writes=apply,
    )

    print("Pending:", result["pending"])
    print("Written:", result["written"])

    if not apply:
        print("DRY RUN ? no writes")
    elif result["verified"]:
        print("PASS: Authorized cells verified")
    else:
        raise RuntimeError("Write verification incomplete")

    print("Checkpoint completion: NOT ATTEMPTED")
    print("Source baseline advancement: NOT ATTEMPTED")
    print("Notifications: DISABLED")
    print("Production PM: UNCHANGED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply-staging", action="store_true")
    args = parser.parse_args()
    main(args.apply_staging)
