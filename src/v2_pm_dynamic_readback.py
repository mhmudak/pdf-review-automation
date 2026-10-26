"""Read-only, header-aware verification of projected PM replies.

No Google I/O. Called on a freshly fetched physical grid, not a canonical
22-column projection. Does not rewrite historical visible reply formatting.
"""
from __future__ import annotations

import re
from collections import Counter
from v2_pm_reply_delta import index, reply_ids, text, validate_global_ids

_REPLY = re.compile(r"Reply ([1-9][0-9]*)\Z")


def verify_dynamic_reply_readback(sheet_values, current_projection, *, previous_projection=None):
    """Verify reply identity and all *new* reply texts after an authorized append.

    Existing displayed replies may differ from source (e.g. approved author
    formatting); never accept unexpected ID edits or missing new reply cells.
    This verifier intentionally does not authorize writes or column changes.
    """
    if not sheet_values:
        raise RuntimeError("PM_EMPTY_GRID")
    headers = [text(x) for x in sheet_values[0]]
    required = ("Root Entry ID", "Reply Entry IDs")
    if any(headers.count(name) != 1 for name in required):
        raise RuntimeError("PM_REPLY_IDENTITY_HEADER_CONFLICT")
    reply_cols = {}
    for i, h in enumerate(headers):
        match = _REPLY.fullmatch(h)
        if match:
            number = int(match.group(1))
            if number in reply_cols:
                raise RuntimeError("PM_DUPLICATE_REPLY_HEADER")
            reply_cols[number] = i
        elif h.startswith("Reply ") and h != "Reply Entry IDs":
            raise RuntimeError("PM_MALFORMED_REPLY_HEADER")
    if sorted(reply_cols) != list(range(1, len(reply_cols) + 1)):
        raise RuntimeError("PM_NON_CONTIGUOUS_REPLY_HEADERS")
    roots_col = headers.index("Root Entry ID")
    ids_col = headers.index("Reply Entry IDs")
    actual = {}
    for raw in sheet_values[1:]:
        root = text(raw[roots_col] if roots_col < len(raw) else "")
        if not root or root in actual:
            raise RuntimeError("PM_ROOT_ID_CONFLICT")
        actual[root] = raw
    current = index(current_projection, "Current")
    previous = index(previous_projection or [], "Previous")
    validate_global_ids(current_projection, "Current")
    if set(actual) != set(current):
        raise RuntimeError("PM_ROOT_SET_CONFLICT")
    if previous_projection is not None and not set(previous).issubset(current):
        raise RuntimeError("SOURCE_ROOT_REMOVAL_REQUIRES_REVIEW")
    count = 0
    for root, projected in current.items():
        raw = actual[root]
        expected_ids = reply_ids(projected)
        actual_ids = reply_ids({"Reply Entry IDs": raw[ids_col] if ids_col < len(raw) else ""})
        if actual_ids != expected_ids:
            raise RuntimeError("PM_REPLY_ID_CONFLICT: " + root)
        if len(expected_ids) > len(reply_cols):
            raise RuntimeError("PM_REPLY_COLUMN_MISSING: " + root)
        old_ids = reply_ids(previous[root]) if root in previous else []
        if root in previous and expected_ids[:len(old_ids)] != old_ids:
            raise RuntimeError("SOURCE_REPLY_ID_REORDER: " + root)
        # New ROOTs: every reply is new. Existing ROOTs: verify new slots only;
        # legacy display text may differ by approved alias/formatting.
        for pos in range(len(old_ids) + 1, len(expected_ids) + 1):
            col = reply_cols[pos]
            displayed = text(raw[col] if col < len(raw) else "")
            target = text(projected.get(f"Reply {pos}"))
            if not target or displayed != target:
                raise RuntimeError("PM_NEW_REPLY_TEXT_CONFLICT: " + root)
            count += 1
    return {"verified": True, "roots": len(current), "new_reply_cells": count, "maximum_reply_depth": len(reply_cols)}
