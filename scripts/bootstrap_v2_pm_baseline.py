"""Bootstrap immutable V2 PM source baseline ? STAGING ONLY."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "src")
)

from sheets_adapter import SheetsAdapter
from v2_output_projection import project_backend_rows

BACKEND = "1DXZJsEG1993iEkzBNJWDAZYhFc2AC2Fm29DTjdYFWIg"
STAGING = "1X4NN9gnvQdXc65cPk9B-p2W-yiBlqZ2rcg8U-ujd2N4"
PM_TAB = "Trial PDF - All Data"
BASELINE_TAB = "_PM_Source_Baseline_V2"

HEADERS = [
    "Root Entry ID",
    "Comment",
    "Reply 1",
    "Reply 2",
    "Reply 3",
    "Reply Entry IDs",
    "Source Row Digest",
    "Snapshot ID",
]


def string(value):
    return "" if value is None else str(value)


def normalized_ids(value):
    return [
        item.strip()
        for item in string(value).replace("|", ",").split(",")
        if item.strip()
    ]


def digest(value):
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def read(adapter, tab, end):
    return adapter.service.spreadsheets().values().get(
        spreadsheetId=adapter.spreadsheet_id,
        range=f"'{tab}'!A1:{end}",
        valueRenderOption="FORMATTED_VALUE",
    ).execute().get("values", [])


def padded(row, width):
    if len(row) > width:
        raise RuntimeError("Unexpected additional columns")
    return list(row) + [""] * (width - len(row))


def collect():
    backend = SheetsAdapter(BACKEND)
    staging = SheetsAdapter(STAGING)

    backend_values = read(backend, "_Entries_V2", "AI")
    if not backend_values:
        raise RuntimeError("Backend entries are empty")

    bh = backend_values[0]
    backend_rows = [
        dict(zip(bh, padded(row, len(bh))))
        for row in backend_values[1:]
    ]

    projection = project_backend_rows(backend_rows)
    projected = projection["rows"]

    pm = read(staging, PM_TAB, "V")
    if not pm or len(pm[0]) != 22:
        raise RuntimeError("Invalid staging PM schema")

    if (
        pm[0][4] != "Comment"
        or pm[0][14] != "Root Entry ID"
        or pm[0][21] != "Reply Entry IDs"
    ):
        raise RuntimeError("Unexpected PM column positions")

    pm_by_id = {}

    for raw in pm[1:]:
        row = padded(raw, 22)
        key = row[14].strip()

        if not key or key in pm_by_id:
            raise RuntimeError("Blank or duplicate PM ROOT ID")

        pm_by_id[key] = row

    projected_by_id = {}

    for row in projected:
        key = string(row.get("Root Entry ID")).strip()

        if not key or key in projected_by_id:
            raise RuntimeError("Blank or duplicate source ROOT ID")

        if string(row.get("Reply 4")).strip():
            raise RuntimeError("Reply 4 requires schema support")

        projected_by_id[key] = row

    if set(pm_by_id) != set(projected_by_id):
        raise RuntimeError("PM/source ROOT identity mismatch")

    source_rows = []
    comment_mismatches = []
    reply_id_mismatches = []

    for root_id in sorted(projected_by_id):
        source = projected_by_id[root_id]
        existing = pm_by_id[root_id]

        comment = string(source.get("Comment"))

        if existing[4] != comment:
            comment_mismatches.append(root_id)

        source_ids = normalized_ids(
            source.get("Reply Entry IDs")
        )
        pm_ids = normalized_ids(existing[21])

        if source_ids != pm_ids:
            reply_id_mismatches.append(root_id)

        values = [
            root_id,
            comment,
            string(source.get("Reply 1")),
            string(source.get("Reply 2")),
            string(source.get("Reply 3")),
            " | ".join(source_ids),
        ]

        source_rows.append(values)

    print("=== SOURCE BASELINE PRECHECK ===")
    print("Source ROOTs:", len(source_rows))
    print("PM ROOTs:", len(pm_by_id))
    print("Comment mismatches:", len(comment_mismatches))
    print("Reply ID mismatches:", len(reply_id_mismatches))
    print(
        "Manual PM categories:",
        sum(bool(row[8].strip()) for row in pm_by_id.values()),
    )

    if comment_mismatches or reply_id_mismatches:
        raise RuntimeError(
            "Source does not match PM identity/comment baseline. "
            "No baseline will be created."
        )

    snapshot_id = digest(source_rows)

    result = [
        [
            *row,
            digest(row),
            snapshot_id,
        ]
        for row in source_rows
    ]

    return staging, [HEADERS, *result], snapshot_id


def main(apply):
    staging, expected, snapshot_id = collect()
    service = staging.service.spreadsheets()

    metadata = service.get(
        spreadsheetId=STAGING,
        fields="sheets(properties(title,sheetId,gridProperties))",
    ).execute()

    matches = [
        sheet["properties"]
        for sheet in metadata.get("sheets", [])
        if sheet["properties"]["title"] == BASELINE_TAB
    ]

    print("Snapshot ID:", snapshot_id)
    print("Existing baseline tab:", bool(matches))

    if matches:
        actual = read(staging, BASELINE_TAB, "H")
        normalized = [
            padded(row, 8) for row in actual
        ]

        if normalized == expected:
            print("NOOP: Verified baseline already stored")
            return

        if normalized:
            raise RuntimeError(
                "Baseline tab contains different or partial data. "
                "Refusing to overwrite historical baseline."
            )

    if not apply:
        print("DRY RUN: No writes performed")
        return

    if not matches:
        service.batchUpdate(
            spreadsheetId=STAGING,
            body={
                "requests": [{
                    "addSheet": {
                        "properties": {
                            "title": BASELINE_TAB,
                            "gridProperties": {
                                "rowCount": len(expected) + 10,
                                "columnCount": 8,
                                "frozenRowCount": 1,
                            },
                        },
                    },
                }],
            },
        ).execute()

    # Refuse if someone populated the new tab in the meantime.
    if read(staging, BASELINE_TAB, "H"):
        raise RuntimeError("Baseline tab changed before write")

    service.values().update(
        spreadsheetId=STAGING,
        range=f"'{BASELINE_TAB}'!A1:H{len(expected)}",
        valueInputOption="RAW",
        body={"values": expected},
    ).execute()

    actual = [
        padded(row, 8)
        for row in read(staging, BASELINE_TAB, "H")
    ]

    if actual != expected:
        raise RuntimeError("Baseline read-back verification failed")

    print("SUCCESS: Source baseline persisted and verified")
    print("Saved ROOTs:", len(expected) - 1)
    print("Snapshot ID:", snapshot_id)
    print("Production PM spreadsheet: UNCHANGED")
    print("No notifications sent")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply-staging",
        action="store_true",
    )
    args = parser.parse_args()
    main(args.apply_staging)
