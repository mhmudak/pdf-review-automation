"""Full changed-version export test on an isolated staging copy.

Real backend source + synthetic changes.
Only writes to a dedicated staging test tab.
Never modifies the production PM or golden staging PM tab.
"""

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "src")
)

import v2_pm_export_coordinator as coordinator

from sheets_adapter import SheetsAdapter
from v2_output_projection import project_backend_rows
from v2_pm_combined_plan import plan_verified_pm_cells
from v2_pm_cell_plan import PM_HEADER_SEQUENCE

BACKEND_ID = "1DXZJsEG1993iEkzBNJWDAZYhFc2AC2Fm29DTjdYFWIg"
STAGING_ID = coordinator.STAGING_ID
SOURCE_TAB = "Trial PDF - All Data"
TEST_TAB = "V2 Full E2E Test"
DOC = "IGCSE_ARABIC_2P"

VERSION_SHA = hashlib.sha256(
    b"props-v2-full-staging-e2e-version-001"
).hexdigest()
VERSION = DOC + "@" + VERSION_SHA

NEW_ROOT = "props-stage-e2e-root-001"
NEW_REPLY = "props-stage-e2e-reply-001"


def build_fixture(backend):
    raw = backend.get_all_values(
        "_Entries_V2", refresh=True
    )
    headers = raw[0]

    records = [
        dict(zip(
            headers,
            coordinator.pad(row, len(headers))
        ))
        for row in raw[1:]
    ]

    records = [
        row for row in records
        if row.get("Document Key") == DOC
    ]

    current = project_backend_rows(records)["rows"]

    no_replies = [
        row for row in current
        if not str(row.get("Reply Entry IDs") or "").strip()
    ]

    if len(no_replies) < 2:
        raise RuntimeError("INSUFFICIENT_TEST_ROOTS")

    comment_root = str(no_replies[0]["Root Entry ID"])
    reply_root = str(no_replies[1]["Root Entry ID"])

    updated = [dict(row) for row in current]

    for row in updated:
        if row["Root Entry ID"] == comment_root:
            row["Comment"] = (
                str(row.get("Comment") or "")
                + " [PROPS E2E TEST REVISION]"
            )

        if row["Root Entry ID"] == reply_root:
            row["Reply 1"] = "Synthetic new PDF reply"
            row["Reply Entry IDs"] = NEW_REPLY

    new_projected = dict(no_replies[0])
    new_projected.update({
        "Root Entry ID": NEW_ROOT,
        "Comment": "Synthetic new ROOT annotation",
        "Reply Entry IDs": "",
        "Reply 1": "",
        "Reply 2": "",
        "Reply 3": "",
        "Book Page": "999",
        "PDF Page": "999",
        "Author": "PrOps Test",
        "Category": "",
    })
    updated.append(new_projected)

    template = next(
        row for row in records
        if (
            row.get("Entry ID") == comment_root
            and row.get("Relation Type", "").upper() == "ROOT"
            and row.get("Active", "").upper() == "TRUE"
        )
    )

    new_backend = dict(template)
    new_backend.update({
        "Entry ID": NEW_ROOT,
        "Root Entry ID": NEW_ROOT,
        "Entry Key": "props-stage-e2e-entry-001",
        "Document Key": DOC,
        "Version ID": VERSION,
        "PDF SHA256": VERSION_SHA,
        "Relation Type": "ROOT",
        "Entry Type": "ROOT",
        "Active": "TRUE",
    })

    records.append(new_backend)

    return {
        "headers": headers,
        "records": records,
        "previous": current,
        "updated": updated,
        "comment_root": comment_root,
        "reply_root": reply_root,
    }


class FixtureBackend:
    """Read-only backend overlay: no production backend writes."""

    def __init__(self, fixture):
        self.fixture = fixture

    def get_all_values(self, tab, refresh=False):
        if tab != "_Entries_V2":
            raise RuntimeError(
                "UNEXPECTED_BACKEND_READ: " + tab
            )

        headers = self.fixture["headers"]

        return [
            headers,
            *[
                [row.get(header, "") for header in headers]
                for row in self.fixture["records"]
            ],
        ]


def ensure_test_tab(staging):
    service = staging.service.spreadsheets()

    result = service.get(
        spreadsheetId=STAGING_ID,
        fields="sheets(properties(sheetId,title))",
    ).execute()

    sheets = {
        item["properties"]["title"]:
        item["properties"]["sheetId"]
        for item in result.get("sheets", [])
    }

    if TEST_TAB in sheets:
        print("Existing E2E test tab reused")
        return

    if SOURCE_TAB not in sheets:
        raise RuntimeError("SOURCE_STAGING_TAB_MISSING")

    service.batchUpdate(
        spreadsheetId=STAGING_ID,
        body={
            "requests": [{
                "duplicateSheet": {
                    "sourceSheetId": sheets[SOURCE_TAB],
                    "newSheetName": TEST_TAB,
                }
            }]
        },
    ).execute()

    print("Created isolated E2E staging tab")


def main(apply):
    backend = SheetsAdapter(BACKEND_ID)
    staging = SheetsAdapter(STAGING_ID)

    fixture = build_fixture(backend)

    original_values = coordinator.read_values(
        staging, SOURCE_TAB, "V"
    )

    if (
        not original_values
        or original_values[0] != PM_HEADER_SEQUENCE
    ):
        raise RuntimeError("SOURCE_PM_SCHEMA_CONFLICT")

    previous = coordinator.read_source_snapshot(
        staging, coordinator.INITIAL_BASELINE
    )

    if (
        coordinator.source_table(previous)
        != coordinator.source_table(fixture["previous"])
    ):
        raise RuntimeError("INITIAL_SOURCE_BASELINE_CHANGED")

    planning = coordinator.prepare_new_root_insertions(
        original_values,
        previous,
        fixture["updated"],
        fixture["records"],
    )

    cells = plan_verified_pm_cells(
        planning["existing_pm_values"],
        previous,
        planning["existing_current_projection"],
    )

    print("=== FULL CHANGED-VERSION INTEGRATION ===")
    print("Previous source ROOTs:", len(previous))
    print("Updated source ROOTs:", len(fixture["updated"]))
    print("New ROOTs:", len(planning["new_rows"]))
    print("Cell updates:", [
        item["cell"]
        for item in cells["cell_update_candidates"]
    ])
    print("Blockers:", len(cells["blockers"]))
    print("Destination:", TEST_TAB)
    print("Apply staging:", apply)

    if cells["blockers"]:
        print("First blockers:", cells["blockers"][:5])
        raise RuntimeError("CHANGED_VERSION_PLAN_BLOCKED")

    if (
        len(planning["new_rows"]) != 1
        or len(cells["cell_update_candidates"]) != 3
    ):
        raise RuntimeError("UNEXPECTED_E2E_CHANGE_PLAN")

    if not apply:
        print("PASS: Combined changed-version plan")
        print("DRY RUN - Google Sheets writes: 0")
        return

    ensure_test_tab(staging)

    # The coordinator is normally hard-locked to the golden
    # staging PM tab. Override it only within this test process
    # to target the isolated copy in the SAME staging spreadsheet.
    previous_tab = coordinator.PM_TAB
    previous_projection_function = (
        coordinator.project_backend_rows
    )

    coordinator.PM_TAB = TEST_TAB
    coordinator.project_backend_rows = lambda records: {
        "headers": [],
        "rows": fixture["updated"],
    }

    try:
        result = coordinator.export_verified_pm(
            backend_sheets=FixtureBackend(fixture),
            output_sheets=None,
            v2_result={
                "document_key": DOC,
                "version_id": VERSION,
                "sha256": VERSION_SHA,
            },
            drive_file=None,
            config={
                "v2_pm_staging_apply": True,
                "v2_pm_output_spreadsheet_id": STAGING_ID,
                "v2_pm_output_tab": TEST_TAB,
            },
        )
    finally:
        coordinator.PM_TAB = previous_tab
        coordinator.project_backend_rows = (
            previous_projection_function
        )

    if result.get("verified") is not True:
        raise RuntimeError("E2E_EXPORT_NOT_VERIFIED")

    destination = coordinator.read_values(
        staging, TEST_TAB, "V"
    )

    verified = coordinator.verify_unchanged_pm(
        destination, fixture["updated"]
    )

    print("Coordinator action:", result["action"])
    print("Export ID:", result["export_id"])
    print("Verified PM ROOTs:", verified)
    print("PASS: Full changed-version export")
    print("Golden staging PM: UNCHANGED")
    print("Production PM: UNCHANGED")
    print("Notifications: DISABLED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply-staging",
        action="store_true",
    )
    args = parser.parse_args()
    main(args.apply_staging)
