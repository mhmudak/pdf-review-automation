from __future__ import annotations

from typing import Any

from registry import RegistryEntry
from sync_engine import (
    files_registry_row,
    sync_annotations,
)
from v2_execution import execute_v2_pdf


def synchronize_processed_pdf(
    *,
    v2_enabled: bool,
    backend_sheets: Any,
    output_sheets: Any,
    config: dict[str, Any],
    annotations: list[dict[str, Any]],
    summary: dict[str, Any],
    drive_file: Any,
    run_id: str,
    master_version: str = "",
) -> dict[str, Any]:
    """
    Route one extracted PDF to either the legacy backend
    or the v2 backend.

    _Files remains the shared lightweight Drive registry.
    """

    if v2_enabled:
        v2_result = execute_v2_pdf(
            sheets=backend_sheets,
            config=config,
            extracted_rows=annotations,
            summary=summary,
            drive_file_id=drive_file.file_id,
            pdf_name=drive_file.name,
            drive_link=drive_file.web_view_link,
            modified_time=drive_file.modified_time,
            size_bytes=drive_file.size,
            master_version=master_version,
        )

        author_summary = v2_result.get(
            "author_summary",
            {},
        )

        entry_changes = v2_result.get(
            "entry_changes",
            {},
        )

        entry_writes = v2_result.get(
            "entry_writes",
            {},
        )

        sync_stats = {
            "inserted": entry_writes.get(
                "inserted",
                0,
            ),
            "updated": entry_writes.get(
                "updated",
                0,
            ),
            "unchanged": entry_changes.get(
                "UNCHANGED",
                0,
            ),
            "skipped": 0,
            "needs_review": (
                author_summary.get(
                    "unresolved_count",
                    0,
                )
            ),
            "output_inserted": 0,
            "output_updated": 0,
            "output_unchanged": 0,
            "author_updated": (
                entry_changes.get(
                    "AUTHOR_UPDATED",
                    0,
                )
            ),
            "removed": entry_changes.get(
                "REMOVED",
                0,
            ),
        }

        duplicate = (
            v2_result.get("action")
            == "DUPLICATE_VERSION"
        )

        status = (
            "DUPLICATE"
            if duplicate
            else "PROCESSED"
        )

        message = (
            "Known v2 document version"
            if duplicate
            else ""
        )

        backend_sheets.append_rows(
            "_Files",
            [
                files_registry_row(
                    drive_file.__dict__.copy(),
                    summary,
                    sync_stats,
                    status,
                    message,
                )
            ],
        )

        return {
            "mode": "V2",
            "sync_stats": sync_stats,
            "duplicate": duplicate,
            "v2_result": v2_result,
        }

    # Legacy path.
    if output_sheets is None:
        raise ValueError(
            "Legacy mode requires output_sheets."
        )

    sync_stats = sync_annotations(
        backend_sheets,
        output_sheets,
        annotations,
        drive_file.file_id,
        drive_file.web_view_link,
        run_id,
        reviewer_tab_map=config.get(
            "reviewer_output_tabs",
            {},
        ),
    )

    backend_sheets.append_rows(
        "_Files",
        [
            files_registry_row(
                drive_file.__dict__.copy(),
                summary,
                sync_stats,
                "PROCESSED",
            )
        ],
    )

    return {
        "mode": "LEGACY",
        "sync_stats": sync_stats,
        "duplicate": False,
        "v2_result": None,
    }


def registry_entry_for_processed_pdf(
    drive_file: Any,
    summary: dict[str, Any],
    *,
    duplicate: bool = False,
) -> RegistryEntry:
    return RegistryEntry(
        file_id=drive_file.file_id,
        name=drive_file.name,
        modified_time=(
            drive_file.modified_time
        ),
        size=drive_file.size,
        sha256=str(
            summary.get(
                "sha256",
                "",
            )
        ),
        status=(
            "DUPLICATE"
            if duplicate
            else "PROCESSED"
        ),
    )
