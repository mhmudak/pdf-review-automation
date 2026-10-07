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

from drive_adapter import DriveAdapter
from extractor import extract_pdf, load_config, load_master_index
from registry import build_registry, precheck
from sheets_adapter import FILES_HEADERS, SheetsAdapter
from sync_engine import files_registry_row, sync_annotations

load_dotenv()


def bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def process_drive_folder(folder_id: str, spreadsheet_id: str, master_index_path: Path, config_path: Path, dry_run: bool = False) -> dict[str, Any]:
    drive = DriveAdapter()
    config = load_config(config_path)
    master_index = load_master_index(master_index_path)
    sheets = None if dry_run else SheetsAdapter(spreadsheet_id)

    by_id, by_md5 = {}, {}
    if sheets:
        sheets.ensure_headers("_Files", FILES_HEADERS)
        by_id, by_md5 = build_registry(sheets.get_all_values("_Files"))

    results = []
    with tempfile.TemporaryDirectory(prefix="workflow2_") as tmp:
        tmpdir = Path(tmp)
        for f in drive.list_pdfs(folder_id):
            if sheets:
                action, reason = precheck(f, by_id, by_md5)
                if action != "PROCESS":
                    results.append({"file_id": f.file_id, "name": f.name, "action": action, "reason": reason})
                    continue

            run_id = str(uuid.uuid4())
            local_pdf = tmpdir / f"{f.file_id}_{f.name}"
            try:
                drive.download(f.file_id, local_pdf)
                annotations, summary = extract_pdf(local_pdf, config, master_index=master_index)
                for a in annotations:
                    a["source_file"] = f.name
                summary["source_file"] = f.name

                if dry_run:
                    sync_stats = {
                        "inserted": sum(1 for a in annotations if a.get("import_candidate")),
                        "updated": 0,
                        "unchanged": 0,
                        "skipped": sum(1 for a in annotations if not a.get("import_candidate")),
                    }
                else:
                    sync_stats = sync_annotations(sheets, annotations, f.file_id, f.web_view_link, run_id)
                    meta = f.__dict__.copy()
                    sheets.append_rows("_Files", [files_registry_row(meta, summary, sync_stats, "PROCESSED")])

                results.append({
                    "file_id": f.file_id,
                    "name": f.name,
                    "action": "PROCESSED",
                    "summary": summary,
                    "sync": sync_stats,
                })
            except Exception as exc:
                if sheets:
                    meta = f.__dict__.copy()
                    empty_summary = {"sha256": "", "reviewers": [], "pages": 0, "pages_mapped": 0, "annotations_found": 0, "skipped_by_reason": {}, "pages_unresolved": [], "footer_mismatches": []}
                    sheets.append_rows("_Files", [files_registry_row(meta, empty_summary, {}, "ERROR", str(exc))])
                results.append({"file_id": f.file_id, "name": f.name, "action": "ERROR", "error": str(exc)})

    return {"files_seen": len(results), "results": results, "dry_run": dry_run}


def main() -> None:
    p = argparse.ArgumentParser(description="Workflow 2 Drive → PDF → Google Sheets pipeline")
    p.add_argument("--folder-id", default=os.getenv("WORKFLOW2_DRIVE_FOLDER_ID", ""))
    p.add_argument("--spreadsheet-id", default=os.getenv("WORKFLOW2_SPREADSHEET_ID", ""))
    p.add_argument("--master-index", type=Path, default=Path(os.getenv("WORKFLOW2_MASTER_INDEX", "master_page_index.json")))
    p.add_argument("--config", type=Path, default=Path(os.getenv("WORKFLOW2_CONFIG", "config.json")))
    p.add_argument("--dry-run", action="store_true", default=bool_env("WORKFLOW2_DRY_RUN"))
    args = p.parse_args()

    if not args.folder_id:
        p.error("Drive folder ID is required")
    if not args.dry_run and not args.spreadsheet_id:
        p.error("Spreadsheet ID is required unless --dry-run is used")
    result = process_drive_folder(args.folder_id, args.spreadsheet_id, args.master_index, args.config, args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
