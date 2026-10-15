"""Safely provision the V2 notification ledger.

Default: READ ONLY.
--apply: create only the dedicated ledger tab or its missing header.
No PM writes and no SMTP activity.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "src")
)

from sheets_adapter import SheetsAdapter
from v2_notification_ledger import TAB, HEADERS, _rows

BACKEND_ID = "1DXZJsEG1993iEkzBNJWDAZYhFc2AC2Fm29DTjdYFWIg"


def provision(*, apply=False):
    adapter = SheetsAdapter(BACKEND_ID)
    api = adapter.service.spreadsheets()

    metadata = api.get(
        spreadsheetId=BACKEND_ID,
        fields="spreadsheetId,sheets(properties(sheetId,title))",
    ).execute()

    if metadata.get("spreadsheetId") != BACKEND_ID:
        raise RuntimeError("BACKEND_IDENTITY_MISMATCH")

    tabs = {
        item["properties"]["title"]:
        item["properties"]["sheetId"]
        for item in metadata.get("sheets", [])
    }

    print("=== NOTIFICATION LEDGER PROVISIONING ===")
    print("Backend ID:", BACKEND_ID)
    print("Ledger tab:", TAB)
    print("Apply enabled:", apply)

    if TAB not in tabs:
        print("Status: LEDGER_TAB_MISSING")

        if not apply:
            print("DRY RUN: would create dedicated hidden tab")
            print("Google Sheets writes: 0")
            return

        api.batchUpdate(
            spreadsheetId=BACKEND_ID,
            body={
                "requests": [{
                    "addSheet": {
                        "properties": {
                            "title": TAB,
                            "hidden": True,
                            "gridProperties": {
                                "rowCount": 1000,
                                "columnCount": len(HEADERS),
                            },
                        }
                    }
                }]
            },
        ).execute()

        print("Created dedicated hidden notification tab")

    response = api.values().get(
        spreadsheetId=BACKEND_ID,
        range=f"'{TAB}'!A1:H1",
        valueRenderOption="FORMULA",
    ).execute()

    existing_header = response.get("values", [])
    actual = existing_header[0] if existing_header else []

    if actual == HEADERS:
        print("Header: VERIFIED")
    elif actual:
        raise RuntimeError(
            "LEDGER_HEADER_CONFLICT: existing header "
            "will not be overwritten"
        )
    elif not apply:
        print("DRY RUN: would write ledger header")
        print("Google Sheets writes: 0")
        return
    else:
        api.values().update(
            spreadsheetId=BACKEND_ID,
            range=f"'{TAB}'!A1:H1",
            valueInputOption="RAW",
            body={"values": [HEADERS]},
        ).execute()
        print("Header created")

    # Read back using the real ledger schema validator.
    records = _rows(adapter)

    print("PASS: Ledger schema verified")
    print("Persisted notification events:", len(records))
    print("PM spreadsheet writes: 0")
    print("Emails sent: 0")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Explicitly authorize ledger provisioning",
    )
    args = parser.parse_args()
    provision(apply=args.apply)
