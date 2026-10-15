"""Read-only production destination readiness audit.

Reads verified staging source and production PM output.
Never changes any spreadsheet, checkpoint, rule or email.
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sheets_adapter import SheetsAdapter
from v2_pm_cell_plan import PM_HEADER_SEQUENCE
from v2_pm_export_coordinator import (
    STAGING_ID,
    INITIAL_BASELINE,
    read_source_snapshot,
    read_values,
    pad,
    ids,
)

PRODUCTION_ID = "13f31vlPWQPWrt2auGukJA7oWrM-90Kp6yU8OhWT3ERE"
PM_TAB = "Trial PDF - All Data"


def index_source(rows):
    result = {}

    for row in rows:
        key = str(row.get("Root Entry ID") or "").strip()

        if not key or key in result:
            raise RuntimeError("SOURCE_ROOT_ID_CONFLICT")

        result[key] = row

    return result


def main():
    staging = SheetsAdapter(STAGING_ID)
    production = SheetsAdapter(PRODUCTION_ID)

    baseline = index_source(
        read_source_snapshot(staging, INITIAL_BASELINE)
    )

    values = read_values(production, PM_TAB, "Z")

    if not values:
        raise RuntimeError("PRODUCTION_PM_EMPTY")

    if values[0][:22] != list(PM_HEADER_SEQUENCE):
        raise RuntimeError("PRODUCTION_PM_SCHEMA_MISMATCH")

    actual = {}
    duplicates = []
    unidentified = []
    extra_columns = []

    for number, raw in enumerate(values[1:], start=2):
        row = pad(raw, 26)
        root_id = row[14].strip()

        if not root_id:
            if any(row):
                unidentified.append(number)
            continue

        if root_id in actual:
            duplicates.append(root_id)

        actual[root_id] = row

        if any(cell.strip() for cell in row[22:26]):
            extra_columns.append(number)

    missing = sorted(set(baseline) - set(actual))
    unexpected = sorted(set(actual) - set(baseline))

    comment_conflicts = []
    reply_id_conflicts = []

    for root_id in sorted(set(actual) & set(baseline)):
        pm = actual[root_id]
        source = baseline[root_id]

        if pm[4] != str(source.get("Comment") or ""):
            comment_conflicts.append(root_id)

        if ids(pm[21]) != ids(
            source.get("Reply Entry IDs")
        ):
            reply_id_conflicts.append(root_id)

    categories = Counter(
        row[8].strip()
        for row in actual.values()
        if row[8].strip()
    )

    print("=== PRoPS V2 PRODUCTION READINESS AUDIT ===")
    print("Mode: READ ONLY")
    print("Verified source ROOTs:", len(baseline))
    print("Production PM ROOTs:", len(actual))
    print("Missing ROOTs:", len(missing))
    print("Unexpected ROOTs:", len(unexpected))
    print("Duplicate ROOT IDs:", len(duplicates))
    print("Unidentified occupied rows:", len(unidentified))
    print("Comment conflicts:", len(comment_conflicts))
    print("Reply ID conflicts:", len(reply_id_conflicts))
    print("Rows with content W:Z:", len(extra_columns))
    print("Manually populated categories:", sum(categories.values()))
    print("Distinct category labels:", len(categories))

    findings = {
        "Missing ROOTs": missing,
        "Unexpected ROOTs": unexpected,
        "Duplicate ROOTs": duplicates,
        "Unidentified occupied rows": unidentified,
        "Comment conflicts": comment_conflicts,
        "Reply ID conflicts": reply_id_conflicts,
        "Rows with additional content": extra_columns,
    }

    for label, items in findings.items():
        if items:
            print(label + " samples:", items[:5])

    critical = [
        missing, unexpected, duplicates, unidentified,
        comment_conflicts, reply_id_conflicts,
    ]

    if any(critical):
        print("STATUS: REVIEW REQUIRED BEFORE PRODUCTION")
    else:
        print("STATUS: SOURCE-OWNED DATA RECONCILED")
        print("Next: explicit production destination authorization")

    print("Production Google Sheets writes: 0")
    print("Staging Google Sheets writes: 0")
    print("Emails sent: 0")


if __name__ == "__main__":
    main()
