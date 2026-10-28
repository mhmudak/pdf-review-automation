"""Conservative, read-only planning for the PrOps V2 PM export."""

from __future__ import annotations

from typing import Any

from v2_pm_reconciliation import reconcile_pm_rows


PROTECTED_FIELDS = frozenset({
    "Author",
    "Category",
    "Reply 1",
    "Reply 2",
    "Reply 3",
    "Reply Entry IDs",
    "PDF Link",
    "Entry Key",
    "Version ID",
    "Drive File ID",
    "PDF SHA256",
    "Original Created Date",
    "Original Modified Date",
})


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def build_pm_export_plan(
    existing_rows: list[dict[str, Any]],
    projected_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Plan only. Never modify the supplied rows or perform writes.

    Existing rows remain authoritative until source-change
    verification and field ownership policies are implemented.
    """
    reconciliation = reconcile_pm_rows(
        existing_rows,
        projected_rows,
    )

    new_rows = reconciliation["new"]
    preserved_rows = reconciliation["preserved"]
    differences = []

    for record in reconciliation["matched"]:
        current = record["existing"]
        proposed = record["projected"]
        entry_id = record["entry_id"]

        for field in proposed:
            if field == "Root Entry ID":
                continue

            if field not in current:
                continue

            before = _text(current.get(field))
            after = _text(proposed.get(field))

            if before == after:
                continue

            differences.append({
                "root_entry_id": entry_id,
                "field": field,
                "classification": (
                    "PROTECTED_DIFFERENCE"
                    if field in PROTECTED_FIELDS
                    or field.startswith("Reply ")
                    else "UNVERIFIED_SOURCE_DIFFERENCE"
                ),
            })

    return {
        "mode": "DRY_RUN",
        "existing_count": reconciliation["existing_count"],
        "projected_count": reconciliation["projected_count"],
        "matched_count": reconciliation["matched_count"],
        "new_count": len(new_rows),
        "preserved_count": len(preserved_rows),
        "new_rows": new_rows,
        "preserved_rows": preserved_rows,
        "differences": differences,
        "write_operations": [],
        "deletion_operations": [],
        "existing_row_updates_authorized": False,
    }
