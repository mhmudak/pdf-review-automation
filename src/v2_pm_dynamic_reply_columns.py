"""Fail-closed planning for V2 dynamic PM reply headers.

This module is deliberately read-only. Structural Sheets changes must be
committed by a separately verified writer before it is connected to export.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from v2_pm_cell_plan import PM_HEADER_SEQUENCE

_REPLY = re.compile(r"Reply ([1-9][0-9]*)\Z")


def _str(value: Any) -> str:
    return "" if value is None else str(value).strip()


def reply_depth(rows: list[dict[str, Any]]) -> int:
    """Return required depth, rejecting gaps and unaccounted reply IDs."""
    max_depth = 3
    for row in rows:
        indices = sorted(
            int(m.group(1)) for field, val in row.items()
            if (m := _REPLY.fullmatch(str(field))) and _str(val)
        )
        if indices and indices != list(range(1, max(indices) + 1)):
            raise ValueError("NON_CONTIGUOUS_REPLY_VALUES")
        raw = _str(row.get("Reply Entry IDs"))
        parsed = [i.strip() for i in raw.replace("|", ",").split(",") if i.strip()]
        if len(parsed) != len(set(parsed)):
            raise ValueError("DUPLICATE_REPLY_IDS")
        if len(parsed) != len(indices):
            raise ValueError("REPLY_TEXT_ID_COUNT_MISMATCH")
        max_depth = max(max_depth, len(indices))
    return max_depth


def plan_reply_column_expansion(physical_rows: list[list[Any]], grid_width: int,
                                projection: list[dict[str, Any]],
                                *, reuse_trailing_blank: bool = False) -> dict[str, Any]:
    """Plan only: append missing Reply N headers AFTER every existing PM column.

    Never inserts within existing data or reuses unnamed cells, to protect
    custom PM columns, their formulas and their physical positions.
    """
    if not physical_rows or grid_width < len(PM_HEADER_SEQUENCE):
        raise ValueError("PM_GRID_STRUCTURE_CONFLICT")
    headers = [_str(x) for x in physical_rows[0]]
    if len(headers) > grid_width:
        raise ValueError("PM_GRID_STRUCTURE_CONFLICT")
    headers += [""] * (grid_width - len(headers))
    counts = Counter(x for x in headers if x)
    required = Counter(PM_HEADER_SEQUENCE)
    for field, count in counts.items():
        if count > required.get(field, 1):
            raise ValueError("PM_DUPLICATE_HEADER")
    for key, number in required.items():
        if counts[key] != number:
            raise ValueError("PM_REQUIRED_HEADER_CONFLICT")
    present = set()
    for field in headers:
        if field.startswith("Reply ") and field != "Reply Entry IDs":
            match = _REPLY.fullmatch(field)
            if not match:
                raise ValueError("MALFORMED_REPLY_HEADER")
            present.add(int(match.group(1)))
    if present != set(range(1, max(present) + 1)):
        raise ValueError("NON_CONTIGUOUS_REPLY_HEADERS")
    for i, header in enumerate(headers):
        if not header and any(i < len(row) and _str(row[i]) for row in physical_rows[1:]):
            raise ValueError("UNNAMED_COLUMN_WITH_DATA")
    depth = reply_depth(projection)
    missing = [f"Reply {i}" for i in range(max(present) + 1, depth + 1)]
    # PM-facing replies must be contiguous immediately after Reply 3.
    # Sheets insertDimension shifts Category and every existing PM-owned
    # column, preserving their values, formulas and formatting.
    first = headers.index("Reply 1")
    if any(headers[first + i - 1] != f"Reply {i}" for i in range(1, max(present) + 1)):
        raise ValueError("PM_REPLY_COLUMNS_NOT_ADJACENT")
    at = first + max(present)
    # A failed insertion may leave unnamed columns precisely at the intended
    # reply location. Reconcile only if the FULL physical column is empty.
    blank = 0
    while at + blank < grid_width and not headers[at + blank]:
        blank += 1
    reusable = min(blank, len(missing))
    if blank and not reuse_trailing_blank and missing:
        raise RuntimeError("PM_BLANK_REPLY_SLOT_REQUIRES_REVIEW")
    reused, inserted = missing[:reusable], missing[reusable:]
    expected = (headers[:at] + reused + inserted + headers[at + reusable:])
    return {
        "mode": "DRY_RUN",
        "existing_grid_width": grid_width,
        "reply_depth": depth,
        "append_headers": inserted,  # compatibility with existing coordinator
        "insert_headers": inserted,
        "reuse_headers": reused,
        "insert_index": at + reusable,
        "new_header_indices": list(range(at, at + len(missing))),
        "expected_headers": expected,
        "google_write_operations": [],
        "requires_structural_write": bool(inserted),
    }
