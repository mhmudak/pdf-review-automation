"""Read-only reconciliation for the PrOps V2 PM sheet.

No Google APIs, mutations, deletion instructions, or writes.
All comparisons use stable Root Entry IDs, never row positions.
"""

from __future__ import annotations

from collections import Counter
from typing import Any


def _identifier(value: Any) -> str:
    return str(value or "").strip()


def _index_rows(
    rows: list[dict[str, Any]],
    id_field: str,
    dataset: str,
) -> dict[str, dict[str, Any]]:
    ids = [_identifier(row.get(id_field)) for row in rows]

    missing = [i + 1 for i, value in enumerate(ids) if not value]
    duplicates = sorted(
        key for key, count in Counter(ids).items()
        if key and count > 1
    )

    if missing or duplicates:
        raise ValueError(
            f"{dataset}: invalid Root Entry IDs; "
            f"missing row indexes={missing[:10]}, "
            f"duplicates={duplicates[:10]}"
        )

    return dict(zip(ids, rows))


def reconcile_pm_rows(
    existing_rows: list[dict[str, Any]],
    projected_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Identify records without producing any write operation.

    Existing PM records are retained in their original order.
    Missing-from-projection records are historical candidates,
    not deletion candidates.
    """

    existing = _index_rows(
        existing_rows, "Root Entry ID", "Existing PM sheet"
    )
    projected = _index_rows(
        projected_rows, "Root Entry ID", "V2 projection"
    )

    existing_ids = set(existing)
    projected_ids = set(projected)

    matched = existing_ids & projected_ids
    new_ids = projected_ids - existing_ids
    preserved_ids = existing_ids - projected_ids

    matched_records = [
        {
            "entry_id": entry_id,
            "existing": dict(existing[entry_id]),
            "projected": dict(projected[entry_id]),
        }
        for entry_id in existing
        if entry_id in matched
    ]

    new_records = [
        dict(row)
        for row in projected_rows
        if _identifier(row.get("Root Entry ID")) in new_ids
    ]

    preserved_records = [
        dict(row)
        for row in existing_rows
        if _identifier(row.get("Root Entry ID")) in preserved_ids
    ]

    return {
        "existing_count": len(existing),
        "projected_count": len(projected),
        "matched_count": len(matched_records),
        "new_count": len(new_records),
        "preserved_count": len(preserved_records),
        "matched": matched_records,
        "new": new_records,
        "preserved": preserved_records,
        "write_operations": [],
        "deletion_operations": [],
        "mode": "DRY_RUN",
    }
