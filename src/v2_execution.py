from __future__ import annotations

from typing import Any

from document_identity import resolve_document_key
from sheets_adapter import SheetsAdapter
from v2_backend import load_v2_snapshot
from v2_registry import apply_v2_registry
from v2_run import prepare_v2_run
from v2_sheet_writer import apply_v2_mutations


def execute_v2_pdf(
    *,
    sheets: SheetsAdapter,
    config: dict[str, Any],
    extracted_rows: list[dict[str, Any]],
    summary: dict[str, Any],
    drive_file_id: str,
    pdf_name: str,
    drive_link: str,
    modified_time: str,
    size_bytes: Any,
    master_version: str = "",
    historical_author_by_entry_id: (
        dict[str, str] | None
    ) = None,
    processed_at: str | None = None,
) -> dict[str, Any]:
    """
    Execute one already-extracted PDF through the v2 backend.

    Important:
    - Drive download/extraction happen before this function.
    - One v2 snapshot is loaded.
    - Change planning is pure.
    - Only changed canonical entries are written.
    - Version/document metadata are then persisted.
    """

    document_key = resolve_document_key(
        config
    )

    sha256 = str(
        summary.get(
            "sha256",
            "",
        )
    ).strip().lower()

    if len(sha256) != 64:
        raise ValueError(
            "Extracted PDF summary must contain "
            "a full 64-character sha256."
        )

    snapshot = load_v2_snapshot(
        sheets
    )

    # Exact same binary for this logical document:
    # do not re-plan or rewrite canonical entries.
    if snapshot.sha_known(
        document_key,
        sha256,
    ):
        return {
            "action": "DUPLICATE_VERSION",
            "document_key": document_key,
            "sha256": sha256,
            "entry_changes": {
                "NEW": 0,
                "UPDATED": 0,
                "AUTHOR_UPDATED": 0,
                "UNCHANGED": 0,
                "REMOVED": 0,
            },
            "entry_writes": {
                "inserted": 0,
                "updated": 0,
                "deactivated": 0,
                "history_appended": 0,
            },
            "registry_writes": {
                "document_inserted": 0,
                "document_updated": 0,
                "version_inserted": 0,
                "version_existing": 1,
            },
        }

    prepared = prepare_v2_run(
        snapshot=snapshot,
        config=config,
        extracted_rows=extracted_rows,
        summary=summary,
        document_key=document_key,
        sha256=sha256,
        drive_file_id=drive_file_id,
        pdf_name=pdf_name,
        drive_link=drive_link,
        modified_time=modified_time,
        size_bytes=size_bytes,
        document_name=str(
            config.get(
                "document_name",
                document_key,
            )
        ).strip(),
        output_tab=str(
            config.get(
                "document_output_tab",
                "",
            )
        ).strip(),
        master_version=master_version,
        historical_author_by_entry_id=(
            historical_author_by_entry_id
        ),
        processed_at=processed_at,
    )

    entry_writes = apply_v2_mutations(
        sheets,
        prepared.mutations,
    )

    registry_writes = apply_v2_registry(
        sheets,
        document_row=prepared.document_row,
        version_row=prepared.version_row,
    )

    return {
        "action": "PROCESSED_V2",
        "document_key":
            prepared.document_key,
        "version_id":
            prepared.version_id,
        "sha256": sha256,
        "author_summary":
            prepared.author_summary,
        "entry_changes":
            prepared.change_plan.counts(),
        "entry_writes":
            entry_writes,
        "registry_writes":
            registry_writes,
    }
