"""Guarded physical-cell application for verified dynamic reply append plans.

Not wired into export_verified_pm. Call only with an independently verified
snapshot and a single serialized writer; Sheets lacks compare-and-swap.
"""
from __future__ import annotations

import re
from v2_pm_safe_writer import CellChange, GuardedPMWriter, parse_cell
from v2_pm_dynamic_reply_cells import plan_dynamic_reply_cells
from v2_pm_column_mapping import PMColumnMapping, letters

_REPLY = re.compile(r"Reply ([1-9][0-9]*)\Z")


class _DynamicMapping:
    """Authorize only managed reply columns and the technical reply-ID field."""
    def __init__(self, base):
        self.base = base
        self.last_column = base.last_column
        self.writable_positions = frozenset(
            index for index, header in enumerate(base.headers)
            if _REPLY.fullmatch(header) or header == "Reply Entry IDs"
        )

    def physical_cell(self, canonical_cell):
        # GuardedPMWriter calls this only to locate the ROOT identity cell.
        if not re.fullmatch(r"O[2-9][0-9]*", canonical_cell):
            raise ValueError("DYNAMIC_MAPPING_ONLY_ROOT_LOOKUP")
        return self.base.physical_cell(canonical_cell)

    def check_headers(self, rows):
        self.base.check_headers(rows)


def apply_dynamic_reply_plan(
    service, spreadsheet_id, tab, *, authorized_spreadsheet_id,
    authorized_tab, sheet_values, grid_width, previous_projection,
    current_projection, approved_author_aliases=None, allow_writes=False,
):
    """Guarded existing-ROOT reply writes; never creates columns or appends ROOTs.

    Caller must re-read the physical grid after any structural header expansion.
    Every planned target is independently rechecked by GuardedPMWriter.
    """
    if spreadsheet_id != authorized_spreadsheet_id or tab != authorized_tab:
        raise PermissionError("DYNAMIC_REPLY_DESTINATION_NOT_AUTHORIZED")
    base = PMColumnMapping.from_rows(sheet_values, grid_width)
    plan = plan_dynamic_reply_cells(
        sheet_values, previous_projection, current_projection,
        approved_author_aliases=approved_author_aliases,
    )
    if plan["blockers"]:
        raise RuntimeError("DYNAMIC_REPLY_PLAN_REQUIRES_REVIEW: " + repr(plan["blockers"][:10]))
    allowed = set()
    for position, header in enumerate(base.headers):
        if _REPLY.fullmatch(header) or header == "Reply Entry IDs":
            allowed.add(position)
    changes = []
    for item in plan["cell_update_candidates"]:
        col, row = parse_cell(item["cell"])
        if col not in allowed or row < 2:
            raise RuntimeError("DYNAMIC_REPLY_UNAUTHORIZED_CELL")
        if base.headers[col] != item["field"]:
            raise RuntimeError("DYNAMIC_REPLY_HEADER_CELL_MISMATCH")
        changes.append(CellChange(
            root_id=item["root_entry_id"], cell=item["cell"],
            expected_value=item["expected_value"],
            new_value=item["new_value"],
        ))
    writer = GuardedPMWriter(
        service, spreadsheet_id, tab,
        authorized_spreadsheet_id=authorized_spreadsheet_id,
        authorized_tab=authorized_tab,
        column_mapping=_DynamicMapping(base),
    )
    result = writer.apply(changes, allow_writes=allow_writes)
    return {**result, "planned_cells": [c.cell for c in changes]}
