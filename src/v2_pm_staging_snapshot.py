"""Create a non-destructive, sorted PM staging snapshot.

No Google API calls. Existing PM rows are preserved by ID.
New ROOT rows are constructed from authoritative V2 metadata.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from v2_pm_cell_plan import PM_HEADER_SEQUENCE

ROOT_ID_COL = 14
CATEGORY_COL = 8
WIDTH = len(PM_HEADER_SEQUENCE)


def string(value: Any) -> str:
    return "" if value is None else str(value)


def identity(value: Any) -> str:
    return string(value).strip()


def validate_pm(values: list[list[Any]]):
    if not values or [
        identity(v) for v in values[0]
    ] != PM_HEADER_SEQUENCE:
        raise ValueError("Unexpected PM 22-column schema")

    result = {}
    for number, raw in enumerate(values[1:], start=2):
        if len(raw) > WIDTH:
            raise ValueError(f"Extra cells in row {number}")

        row = list(raw) + [""] * (WIDTH - len(raw))
        key = identity(row[ROOT_ID_COL])

        if not key or key in result:
            raise ValueError(
                f"Missing/duplicate ROOT ID at row {number}"
            )
        result[key] = row

    return result


def new_root_row(projected, backend):
    if identity(backend.get("Relation Type")).upper() != "ROOT":
        raise ValueError("New entry must be a ROOT")
    if identity(backend.get("Active")).upper() != "TRUE":
        raise ValueError("New ROOT must be active")

    root_id = identity(projected.get("Root Entry ID"))
    if root_id != identity(backend.get("Entry ID")):
        raise ValueError("Projected/backend ROOT ID mismatch")

    required = (
        "Entry Key", "Document Key", "Version ID",
        "Drive File ID", "PDF SHA256",
    )
    if any(not identity(backend.get(k)) for k in required):
        raise ValueError("New ROOT is missing source metadata")

    row = [""] * WIDTH
    mapped = {
        0: projected.get("Book Page"),
        1: projected.get("PDF Page"),
        2: projected.get("Author"),
        3: projected.get("Last Modified"),
        4: projected.get("Comment"),
        5: projected.get("Reply 1"),
        6: projected.get("Reply 2"),
        7: projected.get("Reply 3"),
        8: projected.get("Category"),
        9: projected.get("Selected Text"),
        10: projected.get("Annotation Type"),
        11: backend.get("Drive Link"),
        12: backend.get("PDF Page"),
        13: backend.get("Modified Date"),
        14: root_id,
        15: backend.get("Entry Key"),
        16: backend.get("Version ID"),
        17: backend.get("Drive File ID"),
        18: backend.get("PDF SHA256"),
        19: backend.get("Created Date"),
        20: backend.get("Modified Date"),
        21: " | ".join(
            x.strip() for x in
            string(projected.get("Reply Entry IDs"))
            .replace("|", ",").split(",")
            if x.strip()
        ),
    }
    for col, value in mapped.items():
        row[col] = string(value)

    # Beyond Reply 3 is not yet supported by this fixed schema.
    if "Reply 4" in projected and identity(projected["Reply 4"]):
        raise ValueError("Dynamic reply columns required")

    return row


def build_sorted_staging_snapshot(
    pm_values: list[list[Any]],
    projection_rows: list[dict[str, Any]],
    backend_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return a snapshot; never change supplied data."""
    existing = validate_pm(pm_values)

    backend_roots = {}
    for row in backend_rows:
        if (
            identity(row.get("Relation Type")).upper() == "ROOT"
            and identity(row.get("Active")).upper() == "TRUE"
        ):
            key = identity(row.get("Entry ID"))
            if not key or key in backend_roots:
                raise ValueError("Duplicate/blank active backend ROOT")
            backend_roots[key] = row

    ids = [
        identity(r.get("Root Entry ID"))
        for r in projection_rows
    ]
    if any(not x for x in ids) or any(
        n > 1 for n in Counter(ids).values()
    ):
        raise ValueError("Duplicate/blank projected ROOT IDs")

    assembled = []
    inserted = []
    preserved = []

    for projected in projection_rows:
        key = identity(projected["Root Entry ID"])
        if key in existing:
            assembled.append(list(existing[key]))
        else:
            if key not in backend_roots:
                raise ValueError("Missing new ROOT in backend")
            assembled.append(
                new_root_row(projected, backend_roots[key])
            )
            inserted.append(key)

    # Historical-only entries are retained at the end,
    # preserving their existing relative order.
    projected_set = set(ids)
    for key, row in existing.items():
        if key not in projected_set:
            assembled.append(list(row))
            preserved.append(key)

    final_ids = [identity(r[ROOT_ID_COL]) for r in assembled]
    expected_ids = set(existing) | projected_set
    if (
        len(final_ids) != len(expected_ids)
        or set(final_ids) != expected_ids
    ):
        raise AssertionError("Staging ROOT identity loss")

    for key in existing:
        found = assembled[final_ids.index(key)]
        if found != existing[key]:
            raise AssertionError(
                "Existing PM row changed during staging"
            )

    return {
        "mode": "STAGING_SNAPSHOT",
        "headers": list(PM_HEADER_SEQUENCE),
        "rows": assembled,
        "existing_count": len(existing),
        "inserted_count": len(inserted),
        "historical_preserved_count": len(preserved),
        "total_count": len(assembled),
        "manual_categories_preserved": sum(
            bool(identity(r[CATEGORY_COL]))
            for r in existing.values()
        ),
        "google_write_operations": [],
        "deletion_operations": [],
    }
