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
from sync_engine import (
    files_registry_row,
    reconcile_output_from_database,
)
from backend_router import (
    registry_entry_for_processed_pdf,
    synchronize_processed_pdf,
)
from historical_authors import (
    load_historical_author_map,
)
from v2_backend import ensure_v2_backend


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

    v2_enabled = bool_env(
        "WORKFLOW2_V2_ENABLED",
        default=False,
    )

    historical_author_by_entry_id = (
        load_historical_author_map(config)
        if v2_enabled
        else {}
    )

    if historical_author_by_entry_id:
        print(
            "Historical author provenance loaded: "
            f"{len(historical_author_by_entry_id)} IDs"
        )

    print(
        "Backend mode: "
        + (
            "V2"
            if v2_enabled
            else "LEGACY"
        )
    )

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

    # -------------------------------------------------
    # LIGHTWEIGHT DRIVE PREFLIGHT
    # -------------------------------------------------

    results: list[dict[str, Any]] = []

    pdf_files = drive.list_pdfs(
        folder_id
    )

    print(
        f"Drive scan complete: "
        f"{len(pdf_files)} PDF(s) found."
    )

    # Nothing in the monitored folder means there is
    # nothing else to initialize or read.
    if not pdf_files:
        return {
            "files_seen": 0,
            "results": [],
            "dry_run": dry_run,
        }

    # Backend source-of-truth adapter.
    # Creating the adapter itself does not read sheet data.
    backend_sheets = (
        None
        if dry_run
        else SheetsAdapter(
            spreadsheet_id
        )
    )

    by_id: dict[str, Any] = {}
    by_sha256: dict[str, Any] = {}

    files_needing_processing = []

    if backend_sheets:
        # Idle-run optimization:
        # read ONLY _Files before deciding whether any
        # expensive work is necessary.
        file_registry_values = (
            backend_sheets.get_all_values(
                "_Files"
            )
        )

        by_id, by_sha256 = build_registry(
            file_registry_values
        )

        for f in pdf_files:
            action, reason = precheck(
                f,
                by_id,
            )

            if action == "PROCESS":
                files_needing_processing.append(
                    f
                )
                continue

            print(
                f"Skipping unchanged PDF: "
                f"{f.name}"
            )

            results.append(
                {
                    "file_id": f.file_id,
                    "name": f.name,
                    "action": action,
                    "reason": reason,
                }
            )

        # Critical cheap-path exit.
        # No database read, no PDF download,
        # no extraction, no output spreadsheet,
        # and no notification work.
        if not files_needing_processing:
            print(
                "Preflight complete: "
                "all PDFs unchanged. "
                "Exiting before heavy backend load."
            )

            return {
                "files_seen": len(pdf_files),
                "results": results,
                "dry_run": dry_run,
            }

        print(
            "Change detected: "
            f"{len(files_needing_processing)} "
            "PDF(s) require processing."
        )

        # Heavy backend state is initialized ONLY now.
        #
        # _Files remains shared by both modes because
        # it is the cheap Drive preflight registry.
        backend_sheets.ensure_headers(
            "_Files",
            FILES_HEADERS,
        )

        if v2_enabled:
            print(
                "Initializing v2 backend schema..."
            )

            ensure_v2_backend(
                backend_sheets
            )

        else:
            backend_sheets.ensure_headers(
                "_Database",
                DATABASE_HEADERS,
            )

            backend_sheets.ensure_headers(
                "_Needs Review",
                NEEDS_REVIEW_HEADERS,
            )

            database_values = (
                backend_sheets.get_all_values(
                    "_Database"
                )
            )

            print(
                "Heavy legacy backend loaded: "
                f"{max(len(database_values) - 1, 0)} "
                "database record(s)."
            )

    else:
        # Dry-run mode has no persistent registry,
        # therefore process every discovered PDF.
        files_needing_processing = list(
            pdf_files
        )

    # Team-facing spreadsheet is also deferred until
    # actual processing is required.
    output_sheets = (
        None
        if (
            dry_run
            or v2_enabled
        )
        else SheetsAdapter(
            output_spreadsheet_id
        )
    )

    with tempfile.TemporaryDirectory(
        prefix="workflow2_"
    ) as tmp:

        tmpdir = Path(tmp)

        for f in files_needing_processing:

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
                # LEGACY FILE-LEVEL SHA256 DUPLICATE CHECK
                # ---------------------------------------------

                if not v2_enabled:

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
                # BACKEND SYNCHRONIZATION
                # ---------------------------------------------

                else:
                    assert (
                        backend_sheets
                        is not None
                    )

                    route_result = (
                        synchronize_processed_pdf(
                            v2_enabled=v2_enabled,
                            backend_sheets=(
                                backend_sheets
                            ),
                            output_sheets=(
                                output_sheets
                            ),
                            config=config,
                            annotations=annotations,
                            summary=summary,
                            drive_file=f,
                            run_id=run_id,
                            master_version=str(
                                master_meta.get(
                                    "version",
                                    "",
                                )
                            ),
                        )
                    )

                    sync_stats = (
                        route_result[
                            "sync_stats"
                        ]
                    )

                    if route_result[
                        "duplicate"
                    ]:
                        duplicate_entry = (
                            registry_entry_for_processed_pdf(
                                f,
                                summary,
                                duplicate=True,
                            )
                        )

                        by_id[
                            f.file_id
                        ] = duplicate_entry

                        if (
                            duplicate_entry.sha256
                        ):
                            by_sha256[
                                duplicate_entry.sha256
                            ] = duplicate_entry

                        v2_result = (
                            route_result.get(
                                "v2_result"
                            )
                            or {}
                        )

                        results.append(
                            {
                                "file_id":
                                    f.file_id,
                                "name":
                                    f.name,
                                "action":
                                    "DUPLICATE_VERSION",
                                "reason":
                                    "Known v2 "
                                    "document version",
                                "v2":
                                    v2_result,
                            }
                        )

                        print(
                            "Skipping known v2 "
                            f"version: {f.name}"
                        )

                        continue

                # ---------------------------------------------
                # SAME-RUN REGISTRY UPDATE
                # ---------------------------------------------

                processed_entry = (
                    registry_entry_for_processed_pdf(
                        f,
                        summary,
                    )
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

    parser.add_argument(
        "--reconcile-output",
        action="store_true",
        help=(
            "Rebuild/reconcile reviewer-facing "
            "tabs from the canonical _Database "
            "without processing Drive PDFs."
        ),
    )

    args = parser.parse_args()

    if args.reconcile_output:

        if not args.spreadsheet_id:
            parser.error(
                "Backend spreadsheet ID "
                "is required for reconciliation"
            )

        if not args.output_spreadsheet_id:
            parser.error(
                "Output spreadsheet ID "
                "is required for reconciliation"
            )

        config = load_config(
            args.config
        )

        backend_sheets = SheetsAdapter(
            args.spreadsheet_id
        )

        output_sheets = SheetsAdapter(
            args.output_spreadsheet_id
        )

        result = (
            reconcile_output_from_database(
                backend_sheets,
                output_sheets,
                reviewer_tab_map=config.get(
                    "reviewer_output_tabs",
                    {},
                ),
            )
        )

        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
            )
        )

        return

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
