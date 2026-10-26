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
    # Only a contiguous, completely empty suffix is eligible. Never fill
    # interior unnamed columns; they may be PM-owned reserved space.
    suffix_start = grid_width
    if reuse_trailing_blank:
        while suffix_start > 0 and not headers[suffix_start - 1]:
            suffix_start -= 1
    reusable = min(len(missing), grid_width - suffix_start)
    reused = missing[:reusable]
    appended = missing[reusable:]
    return {
        "mode": "DRY_RUN",
        "existing_grid_width": grid_width,
        "reply_depth": depth,
        "append_headers": appended,
        "reuse_headers": reused,
        "reused_header_indices": list(range(suffix_start, suffix_start + reusable)),
        "new_header_indices": list(range(suffix_start, grid_width + len(appended))),
        "expected_headers": headers[:suffix_start] + reused
            + headers[suffix_start + reusable:] + appended,
        "google_write_operations": [],
        "requires_structural_write": bool(appended),
    }
