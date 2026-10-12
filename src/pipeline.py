#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from alerts import classify_pdf_result
from notifier import notify_alert
from drive_adapter import DriveAdapter
from extractor import (
    assess_master_compatibility,
    extract_pdf,
    load_config,
    load_master_index,
    master_index_metadata,
)
from registry import (
    RegistryEntry,
    build_registry,
    hash_precheck,
    precheck,
)
from sheets_adapter import (
    DATABASE_HEADERS,
    FILES_HEADERS,
    NEEDS_REVIEW_HEADERS,
    SheetsAdapter,
)
from sync_engine import files_registry_row, sync_annotations


load_dotenv()


def bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)

    if raw is None:
        return default

    return raw.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)

        if value:
            return value

    return default


def process_drive_folder(
    folder_id: str,
    spreadsheet_id: str,
    output_spreadsheet_id: str,
    master_index_path: Path,
    config_path: Path,
    dry_run: bool = False,
) -> dict[str, Any]:

    drive = DriveAdapter()

    config = load_config(config_path)
    master_index = load_master_index(master_index_path)

    master_meta = master_index_metadata(
        master_index_path,
        master_index,
    )

    print(
        "Master index loaded: "
        f"version={master_meta['version']} "
        f"| expected_pages={master_meta['expected_pages']} "
        f"| fingerprints={master_meta['fingerprint_count']}"
    )

    # Backend source-of-truth spreadsheet:
    # _Database / _Files / _Needs Review / _Config
    backend_sheets = (
        None
        if dry_run
        else SheetsAdapter(
            spreadsheet_id
        )
    )

    # Team-facing spreadsheet:
    # reviewer tabs only
    output_sheets = (
        None
        if dry_run
        else SheetsAdapter(
            output_spreadsheet_id
        )
    )

    by_id: dict[str, Any] = {}
    by_sha256: dict[str, Any] = {}

    if backend_sheets:
        print(
            "Preflight: validating backend Google Sheets state..."
        )

        backend_sheets.ensure_headers(
            "_Files",
            FILES_HEADERS,
        )

        backend_sheets.ensure_headers(
            "_Database",
            DATABASE_HEADERS,
        )

        backend_sheets.ensure_headers(
            "_Needs Review",
            NEEDS_REVIEW_HEADERS,
        )

        # Read once at startup.
        # SheetsAdapter keeps this cached for the execution.
        database_values = backend_sheets.get_all_values(
            "_Database"
        )

        print(
            "Preflight: _Database loaded "
            f"({max(len(database_values) - 1, 0)} records)."
        )

        file_registry_values = (
            backend_sheets.get_all_values(
                "_Files"
            )
        )

        by_id, by_sha256 = build_registry(
            file_registry_values
        )

    results: list[dict[str, Any]] = []

    pdf_files = drive.list_pdfs(folder_id)

    print(
        f"Drive scan complete: {len(pdf_files)} PDF(s) found."
    )

    with tempfile.TemporaryDirectory(
        prefix="workflow2_"
    ) as tmp:

        tmpdir = Path(tmp)

        for f in pdf_files:

            # -------------------------------------------------
            # PRE-DOWNLOAD DRIVE-LEVEL CHECK
            # -------------------------------------------------

            if backend_sheets:
                action, reason = precheck(
                    f,
                    by_id,
                )

                if action != "PROCESS":
                    print(
                        f"Skipping unchanged PDF: {f.name}"
                    )

                    results.append(
                        {
                            "file_id": f.file_id,
                            "name": f.name,
                            "action": action,
                            "reason": reason,
                        }
                    )

                    continue

            run_id = str(uuid.uuid4())

            local_pdf = (
                tmpdir
                / f"{f.file_id}_{f.name}"
            )

            print(
                f"Processing PDF: {f.name}"
            )

            try:
                # ---------------------------------------------
                # DOWNLOAD + EXTRACTION
                # ---------------------------------------------

                drive.download(
                    f.file_id,
                    local_pdf,
                )

                annotations, summary = extract_pdf(
                    local_pdf,
                    config,
                    master_index=master_index,
                )

                master_assessment = (
                    assess_master_compatibility(
                        summary,
                        master_meta,
                    )
                )

                summary.update(
                    master_assessment
                )

                # ---------------------------------------------
                # FILE-LEVEL SHA256 DUPLICATE CHECK
                # ---------------------------------------------

                hash_action, hash_reason = (
                    hash_precheck(
                        summary.get(
                            "sha256",
                            "",
                        ),
                        f.file_id,
                        by_sha256,
                    )
                )

                if hash_action != "PROCESS":

                    print(
                        f"Skipping duplicate PDF: {f.name} "
                        f"| {hash_reason}"
                    )

                    if backend_sheets:
                        meta = (
                            f.__dict__.copy()
                        )

                        backend_sheets.append_rows(
                            "_Files",
                            [
                                files_registry_row(
                                    meta,
                                    summary,
                                    {},
                                    "DUPLICATE",
                                    hash_reason,
                                )
                            ],
                        )

                    # Update the in-memory Drive-ID registry so
                    # this duplicate is skipped immediately if
                    # encountered again during the same run.
                    duplicate_entry = RegistryEntry(
                        file_id=f.file_id,
                        name=f.name,
                        modified_time=f.modified_time,
                        size=f.size,
                        sha256=summary.get(
                            "sha256",
                            "",
                        ),
                        status="DUPLICATE",
                    )

                    by_id[
                        f.file_id
                    ] = duplicate_entry

                    results.append(
                        {
                            "file_id": f.file_id,
                            "name": f.name,
                            "action": hash_action,
                            "reason": hash_reason,
                        }
                    )

                    continue

                print(
                    "Mapping assessment: "
                    f"{summary.get('pages_mapped', 0)}/"
                    f"{summary.get('pages', 0)} "
                    f"| coverage="
                    f"{summary.get('mapping_coverage', 0):.1%} "
                    f"| beyond_master="
                    f"{summary.get('pages_beyond_master', 0)} "
                    f"| mismatch_suspected="
                    f"{summary.get('master_mismatch_suspected', False)}"
                )

                for annotation in annotations:
                    annotation[
                        "source_file"
                    ] = f.name

                summary[
                    "source_file"
                ] = f.name

                # ---------------------------------------------
                # DRY RUN
                # ---------------------------------------------

                if dry_run:
                    sync_stats = {
                        "inserted": sum(
                            1
                            for annotation
                            in annotations
                            if annotation.get(
                                "import_candidate"
                            )
                        ),
                        "updated": 0,
                        "unchanged": 0,
                        "skipped": sum(
                            1
                            for annotation
                            in annotations
                            if not annotation.get(
                                "import_candidate"
                            )
                        ),
                        "needs_review": 0,
                        "output_inserted": 0,
                        "output_updated": 0,
                        "output_unchanged": 0,
                    }

                # ---------------------------------------------
                # BACKEND + OUTPUT SYNCHRONIZATION
                # ---------------------------------------------

                else:
                    assert (
                        backend_sheets
                        is not None
                    )

                    assert (
                        output_sheets
                        is not None
                    )

                    sync_stats = sync_annotations(
                        backend_sheets,
                        output_sheets,
                        annotations,
                        f.file_id,
                        f.web_view_link,
                        run_id,
                        reviewer_tab_map=config.get(
                            "reviewer_output_tabs",
                            {},
                        ),
                    )

                    meta = (
                        f.__dict__.copy()
                    )

                    backend_sheets.append_rows(
                        "_Files",
                        [
                            files_registry_row(
                                meta,
                                summary,
                                sync_stats,
                                "PROCESSED",
                            )
                        ],
                    )

                # ---------------------------------------------
                # SAME-RUN REGISTRY UPDATE
                # ---------------------------------------------

                processed_entry = RegistryEntry(
                    file_id=f.file_id,
                    name=f.name,
                    modified_time=f.modified_time,
                    size=f.size,
                    sha256=summary.get(
                        "sha256",
                        "",
                    ),
                    status="PROCESSED",
                )

                by_id[
                    f.file_id
                ] = processed_entry

                if processed_entry.sha256:
                    by_sha256[
                        processed_entry.sha256
                    ] = processed_entry

                print(
                    f"Processed successfully: {f.name} "
                    f"| annotations="
                    f"{summary.get('annotations_found', 0)} "
                    f"| db_new="
                    f"{sync_stats.get('inserted', 0)} "
                    f"| db_updated="
                    f"{sync_stats.get('updated', 0)} "
                    f"| db_unchanged="
                    f"{sync_stats.get('unchanged', 0)} "
                    f"| output_new="
                    f"{sync_stats.get('output_inserted', 0)} "
                    f"| output_updated="
                    f"{sync_stats.get('output_updated', 0)} "
                    f"| output_unchanged="
                    f"{sync_stats.get('output_unchanged', 0)}"
                )

                # ---------------------------------------------
                # ALERT CLASSIFICATION + NOTIFICATIONS
                # ---------------------------------------------

                alerts = classify_pdf_result(
                    f.name,
                    summary,
                    sync_stats,
                    status="PROCESSED",
                )

                for alert in alerts:
                    print(
                        "ALERT "
                        f"[{alert['severity']}] "
                        f"[{','.join(alert['audience'])}] "
                        f"{alert['code']}: "
                        f"{alert['message']}"
                    )

                    try:
                        notification_result = (
                            notify_alert(
                                alert
                            )
                        )

                        print(
                            "NOTIFICATION "
                            f"{alert['code']}: "
                            f"{notification_result}"
                        )

                    except Exception as notification_exc:
                        # Notification failure must never make
                        # successful PDF processing fail.
                        print(
                            "WARNING: notification failed "
                            f"for {alert['code']}: "
                            f"{type(notification_exc).__name__}: "
                            f"{notification_exc}"
                        )

                results.append(
                    {
                        "file_id": f.file_id,
                        "name": f.name,
                        "action": "PROCESSED",
                        "summary": summary,
                        "sync": sync_stats,
                        "alerts": alerts,
                    }
                )

            # -------------------------------------------------
            # PDF PROCESSING ERROR
            # -------------------------------------------------

            except Exception as exc:
                print(
                    f"ERROR processing {f.name}: "
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )

                if backend_sheets:
                    try:
                        meta = (
                            f.__dict__.copy()
                        )

                        empty_summary = {
                            "sha256": "",
                            "reviewers": [],
                            "pages": 0,
                            "pages_mapped": 0,
                            "annotations_found": 0,
                            "skipped_by_reason": {},
                            "pages_unresolved": [],
                            "footer_mismatches": [],
                        }

                        backend_sheets.append_rows(
                            "_Files",
                            [
                                files_registry_row(
                                    meta,
                                    empty_summary,
                                    {},
                                    "ERROR",
                                    str(exc),
                                )
                            ],
                        )

                    except Exception as logging_exc:
                        # Never hide the original PDF-processing
                        # error because error logging also failed.
                        print(
                            "WARNING: could not write the "
                            "_Files error record: "
                            f"{type(logging_exc).__name__}: "
                            f"{logging_exc}"
                        )

                alerts = classify_pdf_result(
                    f.name,
                    {},
                    {},
                    status="ERROR",
                    error=str(exc),
                )

                for alert in alerts:
                    print(
                        "ALERT "
                        f"[{alert['severity']}] "
                        f"[{','.join(alert['audience'])}] "
                        f"{alert['code']}: "
                        f"{alert['message']}"
                    )

                    try:
                        notification_result = (
                            notify_alert(
                                alert
                            )
                        )

                        print(
                            "NOTIFICATION "
                            f"{alert['code']}: "
                            f"{notification_result}"
                        )

                    except Exception as notification_exc:
                        print(
                            "WARNING: notification failed "
                            f"for {alert['code']}: "
                            f"{type(notification_exc).__name__}: "
                            f"{notification_exc}"
                        )

                results.append(
                    {
                        "file_id": f.file_id,
                        "name": f.name,
                        "action": "ERROR",
                        "error": str(exc),
                        "alerts": alerts,
                    }
                )

    return {
        "files_seen": len(
            pdf_files
        ),
        "results": results,
        "dry_run": dry_run,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Workflow 2 Drive -> PDF -> "
            "backend + reviewer output pipeline"
        )
    )

    parser.add_argument(
        "--folder-id",
        default=env_first(
            "WORKFLOW2_DRIVE_FOLDER_ID",
            "GOOGLE_DRIVE_FOLDER_ID",
        ),
    )

    parser.add_argument(
        "--spreadsheet-id",
        default=env_first(
            "WORKFLOW2_SPREADSHEET_ID",
            "GOOGLE_SHEETS_SPREADSHEET_ID",
        ),
    )

    parser.add_argument(
        "--output-spreadsheet-id",
        default=env_first(
            "WORKFLOW2_OUTPUT_SPREADSHEET_ID",
            "OUTPUT_SPREADSHEET_ID",
        ),
    )

    parser.add_argument(
        "--master-index",
        type=Path,
        default=Path(
            env_first(
                "WORKFLOW2_MASTER_INDEX",
                default="master_page_index.json",
            )
        ),
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=Path(
            env_first(
                "WORKFLOW2_CONFIG",
                default="config.json",
            )
        ),
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=bool_env(
            "WORKFLOW2_DRY_RUN"
        ),
    )

    args = parser.parse_args()

    if not args.folder_id:
        parser.error(
            "Drive folder ID is required"
        )

    if (
        not args.dry_run
        and not args.spreadsheet_id
    ):
        parser.error(
            "Backend spreadsheet ID is required "
            "unless --dry-run is used"
        )

    if (
        not args.dry_run
        and not args.output_spreadsheet_id
    ):
        parser.error(
            "Output spreadsheet ID is required "
            "unless --dry-run is used"
        )

    result = process_drive_folder(
        args.folder_id,
        args.spreadsheet_id,
        args.output_spreadsheet_id,
        args.master_index,
        args.config,
        args.dry_run,
    )

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()