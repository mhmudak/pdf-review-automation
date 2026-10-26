"""Read-only, header-aware plans for appending PDF replies into PM cells.

No Sheets calls. Only append a single missing reply on an existing ROOT,
with stable existing reply IDs/text. Source changes and destination edits
fail closed. Columns may be reordered and include PM-owned custom fields.
"""
from __future__ import annotations
import re
from v2_pm_reply_delta import reply_ids, index, text, validate_global_ids

_REPLY = re.compile(r"Reply ([1-9][0-9]*)\Z")


def column_name(index_zero):
    result = ""
    n = index_zero + 1
    while n:
        n, digit = divmod(n - 1, 26)
        result = chr(65 + digit) + result
    return result


def _verified_alias_display(old, new, approved_aliases):
    """Accept only an approved replacement of the *leading author token*.

    Body, timestamp, punctuation and whitespace are otherwise untouched.
    """
    if old == new:
        return True
    for raw, canonical in (approved_aliases or {}).items():
        raw, canonical = str(raw), str(canonical)
        if raw and canonical and old.startswith(raw + " "):
            if new == canonical + old[len(raw):]:
                return True
    return False


def plan_dynamic_reply_cells(sheet_values, previous_projection, current_projection,
                             *, approved_author_aliases=None):
    if not sheet_values:
        raise ValueError("EMPTY_PM_GRID")
    headers = [text(x) for x in sheet_values[0]]
    from collections import Counter
    from v2_pm_cell_plan import PM_HEADER_SEQUENCE
    expected = Counter(PM_HEADER_SEQUENCE)
    observed = Counter(x for x in headers if x)
    if any(count > expected.get(name, 1) for name, count in observed.items()):
        raise ValueError("DUPLICATE_PM_HEADER")
    required = ["Root Entry ID", "Reply Entry IDs"]
    if any(headers.count(name) != 1 for name in required):
        raise ValueError("PM_IDENTITY_HEADER_MISSING")
    columns = {}
    for i, name in enumerate(headers):
        match = _REPLY.fullmatch(name)
        if match:
            columns[int(match.group(1))] = i
        elif name.startswith("Reply ") and name != "Reply Entry IDs":
            raise ValueError("MALFORMED_REPLY_HEADER")
    if sorted(columns) != list(range(1, len(columns) + 1)):
        raise ValueError("NON_CONTIGUOUS_REPLY_HEADERS")
    pm_index = headers.index("Root Entry ID")
    id_index = headers.index("Reply Entry IDs")
    by_root = {}
    for row_num, row in enumerate(sheet_values[1:], start=2):
        root = text(row[pm_index] if pm_index < len(row) else "")
        if not root or root in by_root:
            raise ValueError("PM_ROOT_ID_CONFLICT")
        by_root[root] = (row_num, row)
    before = index(previous_projection, "Previous")
    after = index(current_projection, "Current")
    validate_global_ids(previous_projection, "Previous")
    validate_global_ids(current_projection, "Current")
    if not set(before).issubset(by_root):
        raise ValueError("PM_PREVIOUS_ROOT_MISSING")
    updates = []
    holds = []
    for root, old in before.items():
        if root not in after:
            holds.append((root, "REMOVED_ROOT"))
            continue
        new = after[root]
        row_num, pm = by_root[root]
        old_ids = reply_ids(old)
        new_ids = reply_ids(new)
        actual_ids = reply_ids({"Reply Entry IDs": pm[id_index] if id_index < len(pm) else ""})
        # A prior guarded batch may have written the reply text and/or
        # technical IDs before an interrupted checkpoint update.  Accept
        # only the exact previous or intended ID sequence, never an
        # arbitrary destination edit.
        if actual_ids not in (old_ids, new_ids):
            holds.append((root, "PM_REPLY_ID_BASELINE_CONFLICT"))
            continue
        if new_ids == old_ids:
            if any(not _verified_alias_display(text(old.get(f"Reply {i}")), text(new.get(f"Reply {i}")), approved_author_aliases)
                   for i in range(1, len(old_ids) + 1)):
                holds.append((root, "EXISTING_REPLY_CHANGED"))
            continue
        if new_ids[:len(old_ids)] != old_ids or len(new_ids) != len(old_ids) + 1:
            holds.append((root, "REPLY_NON_SINGLE_APPEND"))
            continue
        if any(not _verified_alias_display(text(old.get(f"Reply {i}")), text(new.get(f"Reply {i}")), approved_author_aliases)
               for i in range(1, len(old_ids) + 1)):
            holds.append((root, "EXISTING_REPLY_CHANGED"))
            continue
        pos = len(new_ids)
        if pos not in columns:
            holds.append((root, "REPLY_COLUMN_NOT_CREATED"))
            continue
        field = f"Reply {pos}"
        value = text(new.get(field))
        col = columns[pos]
        actual_text = text(pm[col] if col < len(pm) else "")
        if not value or actual_text not in ("", value):
            holds.append((root, "NEW_REPLY_TARGET_CONFLICT"))
            continue
        # Never authorize writing an existing reply or unrelated cell.
        # GuardedPMWriter performs its own formula and ROOT validation.
        if actual_text != value:
            updates.append({
                "root_entry_id": root, "field": field,
                "cell": f"{column_name(col)}{row_num}",
                "expected_value": "", "new_value": value,
            })
        if actual_ids != new_ids:
            updates.append({
                "root_entry_id": root, "field": "Reply Entry IDs",
                "cell": f"{column_name(id_index)}{row_num}",
                "expected_value": pm[id_index] if id_index < len(pm) else "",
                "new_value": " | ".join(new_ids),
            })
    return {"mode": "DRY_RUN", "cell_update_candidates": [] if holds else updates, "blockers": holds, "google_write_operations": []}
