"""Cloud Run Job one-shot entrypoint for PDF Review Automation V2.

This is deliberately separate from the HTTP service entrypoint. The job
must terminate after one execution so Cloud Run can record its outcome.
"""
from __future__ import annotations

import json
import os
import sys


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def run_once(pipeline_fn=None) -> dict:
    """One invocation; production email requires separate exact authorization."""
    if not _enabled("WORKFLOW2_V2_ENABLED"):
        raise RuntimeError("JOB_REQUIRES_EXPLICIT_V2_MODE")

    # Fail closed BEFORE importing the pipeline or touching Drive/Sheets.
    notifications_on = _enabled("NOTIFICATIONS_ENABLED")
    mode = os.getenv("NOTIFICATION_MODE", "OFF").strip().upper()
    if notifications_on:
        from v2_production_notification_gate import (
            ensure_notification_delivery_authorized,
        )
        ensure_notification_delivery_authorized(
            destination=os.getenv("WORKFLOW2_OUTPUT_SPREADSHEET_ID", ""),
            mode=mode,
            notifications_on=True,
            dry_run=_enabled("WORKFLOW2_DRY_RUN"),
            verified_export_required=True,  # Config verified again in pipeline.
        )

    if pipeline_fn is None:
        from http_service import _run_pipeline
        pipeline_fn = _run_pipeline

    result = pipeline_fn()
    if not isinstance(result, dict):
        raise RuntimeError("JOB_RESULT_NOT_A_DICTIONARY")
    return result


def main() -> int:
    try:
        result = run_once()
        rows = result.get("results", [])
        errors = sum(
            item.get("action") == "ERROR"
            for item in rows if isinstance(item, dict)
        )
        print(json.dumps({
            "job": "pdf-review-automation",
            "files_seen": result.get("files_seen"),
            "result_count": len(rows),
            "error_count": errors,
        }, sort_keys=True), flush=True)
        # Pipeline records errors per-file instead of always raising.
        # Cloud Run must not report success for partial processing failures.
        return 1 if errors else 0
    except Exception as exc:
        print(
            "PDF_JOB_FAILED: " + type(exc).__name__ + ": " + str(exc),
            file=sys.stderr,
            flush=True,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
