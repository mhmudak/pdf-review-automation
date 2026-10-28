from __future__ import annotations

from typing import Any

from author_review import (
    build_author_review_rows,
    promote_approved_author_reviews,
    upsert_author_review_rows,
)
from document_identity import resolve_document_key
from sheets_adapter import SheetsAdapter
from v2_backend import load_v2_snapshot
from v2_registry import apply_v2_registry
from v2_run import prepare_v2_run
from v2_sheet_writer import apply_v2_mutations


def reject_removed_active_roots(prepared: Any) -> None:
    """Fail closed before writes when a new PDF removes existing ROOTs.

    The PM exporter must never be the first layer to discover
    a destructive source change: backend mutations precede export.
    """
    for change in prepared.change_plan.removed:
        previous = change.previous or {}
        relation = str(previous.get("Relation Type", "")).strip().upper()
        active = str(previous.get("Active", "TRUE")).strip().upper()
        if relation == "ROOT" and active not in {"FALSE", "0", "NO", ""}:
            raise RuntimeError("SOURCE_ROOT_REMOVAL_REQUIRES_REVIEW")


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

    known_sha = snapshot.sha_known(
        document_key,
        sha256,
    )

    # Even for an already-known PDF binary we still
    # prepare/resolve entries. This is necessary because
    # a PM may have approved a new author rule after the
    # original ingestion.
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

    # Guard source integrity before any approval or backend mutation.
    if config.get("v2_require_verified_pm_export") is True:
        reject_removed_active_roots(prepared)

    approval_sync = {
        "approved_found": 0,
        "inserted": 0,
        "existing": 0,
    }

    # If anything is unresolved, check whether the PM
    # has approved an existing review item since the
    # previous run.
    if (
        prepared.author_summary.get(
            "unresolved_count",
            0,
        )
        > 0
    ):
        approval_sync = (
            promote_approved_author_reviews(
                sheets
            )
        )

        if approval_sync["inserted"]:
            # Reload decision-grade state so the newly
            # promoted rules participate immediately.
            snapshot = load_v2_snapshot(
                sheets,
                refresh=True,
            )

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

    # Recheck after author-rule promotion may replan the entries.
    if config.get("v2_require_verified_pm_export") is True:
        reject_removed_active_roots(prepared)

    review_rows = build_author_review_rows(
        list(prepared.entries)
    )

    review_sync = upsert_author_review_rows(
        sheets,
        review_rows,
    )

    if known_sha:
        counts = prepared.change_plan.counts()

        structural_changes = (
            counts.get("NEW", 0)
            + counts.get("UPDATED", 0)
            + counts.get("REMOVED", 0)
        )

        author_updates = counts.get(
            "AUTHOR_UPDATED",
            0,
        )

        if structural_changes:
            raise ValueError(
                "Known PDF SHA produced structural "
                "entry changes. Refusing to mutate v2 "
                "state because identical binary content "
                "must not create NEW/UPDATED/REMOVED "
                "entries."
            )

        if author_updates == 0:
            return {
                "action": "DUPLICATE_VERSION",
                "document_key": document_key,
                "version_id":
                    prepared.version_id,
                "sha256": sha256,
                "author_summary":
                    prepared.author_summary,
                "entry_changes": counts,
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
                "author_review": review_sync,
                "author_rule_promotion":
                    approval_sync,
            }

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
        "author_review":
            review_sync,
        "author_rule_promotion":
            approval_sync,
    }
