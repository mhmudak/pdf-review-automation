"""Real V2 backend -> staging coordinator integration.

Default: read-only. --apply-staging permits checkpoint and
immutable snapshot writes in the authorized staging spreadsheet.
Never writes to the production PM destination.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "src")
)

from sheets_adapter import SheetsAdapter
from v2_output_projection import project_backend_rows
from v2_pm_export_coordinator import (
    STAGING_ID,
    PM_TAB,
    INITIAL_BASELINE,
    source_table,
    read_source_snapshot,
    export_verified_pm,
    ids,
    pad,
    read_values,
)

BACKEND_ID = "1DXZJsEG1993iEkzBNJWDAZYhFc2AC2Fm29DTjdYFWIg"
DOCUMENT_KEY = "IGCSE_ARABIC_2P"


def as_records(values):
    if not values:
        raise RuntimeError("EMPTY_BACKEND_TABLE")
    headers = values[0]
    if not headers or len(headers) != len(set(headers)):
        raise RuntimeError("INVALID_BACKEND_HEADERS")
    return [
        dict(zip(headers, pad(row, len(headers))))
        for row in values[1:]
    ]


def main(apply):
    backend = SheetsAdapter(BACKEND_ID)
    staging = SheetsAdapter(STAGING_ID)

    docs = as_records(
        backend.get_all_values("_Documents", refresh=True)
    )

    matches = [
        row for row in docs
        if row["Document Key"] == DOCUMENT_KEY
    ]

    if len(matches) != 1:
        raise RuntimeError(
            "Expected exactly one backend document"
        )

    doc = matches[0]
    version = doc["Current Version ID"].strip()
    sha = doc["Current PDF SHA256"].strip()

    if not version or len(sha) != 64:
        raise RuntimeError("INVALID_CURRENT_BACKEND_VERSION")

    entries = as_records(
        backend.get_all_values("_Entries_V2", refresh=True)
    )

    entries = [
        row for row in entries
        if row["Document Key"] == DOCUMENT_KEY
    ]

    current = project_backend_rows(entries)["rows"]

    previous = read_source_snapshot(
        staging, INITIAL_BASELINE
    )

    if source_table(previous) != source_table(current):
        raise RuntimeError(
            "SOURCE_CHANGED_SINCE_BASELINE: "
            "Do not bootstrap another baseline or write PM data."
        )

    pm_values = read_values(staging, PM_TAB, "V")
    pm_by_id = {}

    for raw in pm_values[1:]:
        row = pad(raw, 22)
        key = row[14].strip()
        if not key or key in pm_by_id:
            raise RuntimeError("INVALID_PM_ROOT_ID")
        pm_by_id[key] = row

    projected = {
        str(row["Root Entry ID"]): row
        for row in current
    }

    if len(projected) != len(current):
        raise RuntimeError("DUPLICATE_PROJECTED_ROOT")

    if set(pm_by_id) != set(projected):
        raise RuntimeError("ROOT_IDENTITY_MISMATCH")

    for key, source in projected.items():
        pm = pm_by_id[key]

        if pm[4] != str(source.get("Comment") or ""):
            raise RuntimeError(
                f"PM_COMMENT_CONFLICT: {key}"
            )

        if ids(pm[21]) != ids(
            source.get("Reply Entry IDs")
        ):
            raise RuntimeError(
                f"PM_REPLY_ID_CONFLICT: {key}"
            )

    print("=== REAL BACKEND COORDINATOR TEST ===")
    print("Document:", DOCUMENT_KEY)
    print("Version ID:", version)
    print("PDF SHA256:", sha)
    print("Current ROOTs:", len(current))
    print("Verified baseline ROOTs:", len(previous))
    print("Staging PM ROOTs:", len(pm_by_id))
    print("Source changes:", 0)
    print("Destination:", "STAGING ONLY")

    if not apply:
        print("READ-ONLY PREFLIGHT PASSED")
        print("No Google Sheets writes performed")
        return

    result = export_verified_pm(
        backend_sheets=backend,
        output_sheets=None,
        v2_result={
            "document_key": DOCUMENT_KEY,
            "version_id": version,
            "sha256": sha,
        },
        drive_file=None,
        config={
            "v2_pm_staging_apply": True,
            "v2_pm_output_spreadsheet_id": STAGING_ID,
            "v2_pm_output_tab": PM_TAB,
        },
    )

    if result.get("verified") is not True:
        raise RuntimeError("COORDINATOR_NOT_VERIFIED")

    print("Coordinator result:", result["action"])
    print("Export ID:", result["export_id"])
    print("Verified:", result["verified"])
    print("Production PM: UNCHANGED")
    print("Notifications: DISABLED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply-staging", action="store_true"
    )
    args = parser.parse_args()
    main(args.apply_staging)
