"""Limit expensive PDF extraction in explicit dry-run testing only.

No effect on normal V2 executions; this function is invoked only when dry_run=True.
"""
from __future__ import annotations

import os


def select_dry_run_pdfs(pdfs: list) -> list:
    raw = os.getenv('WORKFLOW2_DRY_RUN_MAX_FILES', '').strip()
    if not raw:
        return pdfs
    try:
        limit = int(raw)
    except ValueError as exc:
        raise ValueError('INVALID_DRY_RUN_MAX_FILES') from exc
    if not 1 <= limit <= 10:
        raise ValueError('INVALID_DRY_RUN_MAX_FILES')
    # Prefer small PDFs for cheap smoke tests, even if Drive returns
    # them after older, much larger PDFs.
    return sorted(
        pdfs,
        key=lambda pdf: (
            pdf.size if getattr(pdf, 'size', 0) > 0 else float('inf'),
            getattr(pdf, 'name', ''),
            getattr(pdf, 'file_id', ''),
        ),
    )[:limit]
