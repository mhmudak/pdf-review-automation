"""One-time, verified, staging-only sorted export."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sheets_adapter import SheetsAdapter
from v2_output_projection import project_backend_rows
from v2_pm_staging_snapshot import build_sorted_staging_snapshot

BACKEND = "1DXZJsEG1993iEkzBNJWDAZYhFc2AC2Fm29DTjdYFWIg"
PRODUCTION = "13f31vlPWQPWrt2auGukJA7oWrM-90Kp6yU8OhWT3ERE"
STAGING = "1X4NN9gnvQdXc65cPk9B-p2W-yiBlqZ2rcg8U-ujd2N4"
TAB = "Trial PDF - All Data"
WIDTH = 22


def read(adapter, tab, end, *, render="FORMATTED_VALUE"):
    result = adapter.service.spreadsheets().values().get(
        spreadsheetId=adapter.spreadsheet_id,
        range=f"'{tab}'!A1:{end}",
        valueRenderOption=render,
    ).execute()
    return result.get("values", [])


def padded(values):
    return [
        [str(v) if v is not None else "" for v in row]
        + [""] * (WIDTH - len(row))
        for row in values
    ]


def row_map(values):
    result = {}
    for row in padded(values[1:]):
        key = row[14].strip()
        if not key or key in result:
            raise ValueError("Missing or duplicate ROOT ID")
        result[key] = row
    return result


def main(apply):
    backend = SheetsAdapter(BACKEND)
    production = SheetsAdapter(PRODUCTION)
    staging = SheetsAdapter(STAGING)

    raw_backend = read(backend, "_Entries_V2", "AI")
    headers = raw_backend[0]
    backend_rows = [
        dict(zip(headers, row + [""] * (len(headers) - len(row))))
        for row in raw_backend[1:]
    ]

    source = read(production, TAB, "V")
    current = read(staging, TAB, "V")

    # A staging copy must match the original by ID and content,
    # independently of the ordering of its rows.
    if row_map(source) != row_map(current):
        raise RuntimeError(
            "Staging and production content differ. "
            "Aborting instead of overwriting staging changes."
        )

    formulas = read(staging, TAB, "V", render="FORMULA")
    if any(
        isinstance(value, str) and value.startswith("=")
        for row in formulas for value in row
    ):
        raise RuntimeError(
            "Formulas detected. Values-only sorting is unsafe."
        )

    projection = project_backend_rows(backend_rows)
    snapshot = build_sorted_staging_snapshot(
        source,
        projection["rows"],
        backend_rows,
    )

    expected = [snapshot["headers"], *snapshot["rows"]]
    expected = padded(expected)

    print("=== VERIFIED STAGING EXPORT ===")
    print("Existing ROOTs:", snapshot["existing_count"])
    print("New ROOTs:", snapshot["inserted_count"])
    print("Historical preserved:",
          snapshot["historical_preserved_count"])
    print("Manual categories:",
          snapshot["manual_categories_preserved"])
    print("Total output ROOTs:", snapshot["total_count"])
    print("Order already correct:",
          padded(current) == expected)

    if not apply:
        print("DRY RUN ? no writes. Use --apply-staging.")
        return

    if padded(current) == expected:
        print("NOOP: Staging already matches desired order.")
        return

    if len(current) != len(expected):
        raise RuntimeError(
            "This staging test requires equal row counts."
        )

    # Final pre-write recheck: reject concurrent changes.
    if row_map(read(staging, TAB, "V")) != row_map(current):
        raise RuntimeError("Staging changed during planning.")

    # Only STAGING is writable in this script.
    service = staging.service.spreadsheets().values()

    for start in range(0, len(expected), 100):
        batch = expected[start:start + 100]
        a1 = f"'{TAB}'!A{start + 1}:V{start + len(batch)}"
        service.update(
            spreadsheetId=STAGING,
            range=a1,
            valueInputOption="RAW",
            body={"values": batch},
        ).execute()

    actual = padded(read(staging, TAB, "V"))
    if actual != expected:
        raise RuntimeError(
            "Staging verification failed. "
            "Do not activate Scheduler."
        )

    if row_map(actual) != row_map(source):
        raise RuntimeError(
            "Identity/content integrity verification failed."
        )

    print("SUCCESS: STAGING sorted and verified.")
    print("Production PM sheet: UNCHANGED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply-staging", action="store_true"
    )
    args = parser.parse_args()
    main(args.apply_staging)
