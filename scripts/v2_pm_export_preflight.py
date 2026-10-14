"""PrOps V2 verified-source export preflight.

Connects durable staging baseline, current backend projection,
PM output and existing source-change/cell planners.

READ ONLY: no Google Sheets writes, checkpoint changes or emails.
"""

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "src")
)

from sheets_adapter import SheetsAdapter
from v2_output_projection import project_backend_rows
from v2_pm_cell_plan import (
    PM_HEADER_SEQUENCE,
    plan_pm_comment_cells,
)
from v2_pm_source_delta import plan_verified_source_delta

BACKEND = "1DXZJsEG1993iEkzBNJWDAZYhFc2AC2Fm29DTjdYFWIg"
STAGING = "1X4NN9gnvQdXc65cPk9B-p2W-yiBlqZ2rcg8U-ujd2N4"
PM_TAB = "Trial PDF - All Data"
BASELINE_TAB = "_PM_Source_Baseline_V2"

BASELINE_HEADERS = [
    "Root Entry ID", "Comment", "Reply 1", "Reply 2",
    "Reply 3", "Reply Entry IDs", "Source Row Digest",
    "Snapshot ID",
]


def text(value):
    return "" if value is None else str(value)


def pad(row, width):
    if len(row) > width:
        raise ValueError("Unexpected extra columns")
    return list(row) + [""] * (width - len(row))


def ids(value):
    return " | ".join(
        item.strip()
        for item in text(value).replace("|", ",").split(",")
        if item.strip()
    )


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def read(adapter, tab, end):
    return adapter.service.spreadsheets().values().get(
        spreadsheetId=adapter.spreadsheet_id,
        range=f"'{tab}'!A1:{end}",
        valueRenderOption="FORMATTED_VALUE",
    ).execute().get("values", [])


def baseline_rows(values):
    if not values or values[0] != BASELINE_HEADERS:
        raise ValueError("Baseline schema mismatch")

    result = []
    snapshot_ids = set()
    seen = set()

    for raw in values[1:]:
        row = pad(raw, 8)
        fields = row[:6]
        root = fields[0].strip()

        if not root or root in seen:
            raise ValueError("Duplicate or blank baseline ROOT")

        seen.add(root)

        if digest(fields) != row[6]:
            raise ValueError(
                f"Baseline row integrity failed: {root}"
            )

        snapshot_ids.add(row[7])
        result.append(fields)

    if len(snapshot_ids) != 1:
        raise ValueError("Inconsistent baseline snapshot IDs")

    if digest(result) != next(iter(snapshot_ids)):
        raise ValueError("Baseline snapshot digest mismatch")

    return [
        {
            "Root Entry ID": r[0],
            "Comment": r[1],
            "Reply 1": r[2],
            "Reply 2": r[3],
            "Reply 3": r[4],
            "Reply Entry IDs": r[5],
        }
        for r in result
    ]


def main():
    backend = SheetsAdapter(BACKEND)
    staging = SheetsAdapter(STAGING)

    baseline = baseline_rows(
        read(staging, BASELINE_TAB, "H")
    )

    raw_backend = read(backend, "_Entries_V2", "AI")
    if not raw_backend:
        raise ValueError("Backend is empty")

    headers = raw_backend[0]
    records = [
        dict(zip(headers, pad(row, len(headers))))
        for row in raw_backend[1:]
    ]

    projection = project_backend_rows(records)
    current = []

    for row in projection["rows"]:
        record = dict(row)
        record["Reply Entry IDs"] = ids(
            record.get("Reply Entry IDs")
        )
        current.append(record)

    pm_values = read(staging, PM_TAB, "V")

    if not pm_values or pm_values[0] != PM_HEADER_SEQUENCE:
        raise ValueError("PM schema mismatch")

    pm = []
    seen_pm = set()

    for raw in pm_values[1:]:
        row = pad(raw, 22)
        root = row[14].strip()

        if not root or root in seen_pm:
            raise ValueError("Duplicate or blank PM ROOT")

        seen_pm.add(root)

        pm.append({
            "Root Entry ID": root,
            "Comment": row[4],
            "Reply 1": row[5],
            "Reply 2": row[6],
            "Reply 3": row[7],
            "Reply Entry IDs": ids(row[21]),
            "Category": row[8],
        })

    plan = plan_verified_source_delta(
        pm, baseline, current
    )

    comments = plan_pm_comment_cells(
        pm_values,
        plan["verified_cell_update_candidates"],
    )

    print("=== PRoPS V2 SOURCE-VERIFIED EXPORT PREFLIGHT ===")
    print("Mode: READ ONLY")
    print("Baseline ROOTs:", len(baseline))
    print("Current projected ROOTs:", len(current))
    print("PM ROOTs:", len(pm))
    print(
        "Verified comment candidates:",
        len(plan["verified_cell_update_candidates"]),
    )
    print(
        "New ROOT candidates:",
        len(plan["new_root_candidates"]),
    )
    print(
        "Held for review:",
        len(plan["held_for_review"]),
    )
    print(
        "Historical ROOTs:",
        len(plan["historical_root_ids"]),
    )
    print(
        "Comment cell updates:",
        len(comments["cell_update_candidates"]),
    )
    print("Cell conflicts:", len(comments["conflicts"]))
    print(
        "Manual categories:",
        sum(bool(r["Category"].strip()) for r in pm),
    )

    if (
        plan["held_for_review"]
        or comments["conflicts"]
    ):
        print("STATUS: REVIEW REQUIRED")
        print("First held items:",
              plan["held_for_review"][:5])
        print("First conflicts:",
              comments["conflicts"][:5])
    elif (
        plan["new_root_candidates"]
        or comments["cell_update_candidates"]
    ):
        print("STATUS: VERIFIED SOURCE CHANGES DETECTED")
        print("No writes performed")
    else:
        print("STATUS: SOURCE BASELINE CURRENT ? NOOP")

    print("Google Sheets writes: 0")
    print("Notifications: 0")
    print("Production PM unchanged")

    return {
        "source_plan": plan,
        "comment_plan": comments,
        "pm_values": pm_values,
    }


if __name__ == "__main__":
    main()
