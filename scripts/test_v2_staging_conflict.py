"""Real staging conflict test; deliberately performs no writes."""

import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "src")
)

from sheets_adapter import SheetsAdapter
from v2_pm_safe_writer import (
    GuardedPMWriter,
    CellChange,
    PMWriteConflict,
)

STAGING = "1X4NN9gnvQdXc65cPk9B-p2W-yiBlqZ2rcg8U-ujd2N4"
TAB = "V2 Integration Tests"

adapter = SheetsAdapter(STAGING)

writer = GuardedPMWriter(
    adapter.service,
    STAGING,
    TAB,
    authorized_spreadsheet_id=STAGING,
    authorized_tab=TAB,
)

root = "props-stage-root-002"

original = writer.read_cell("E3")
category_before = writer.read_cell("I2")

# Deliberately WRONG expectation.
# The cell now contains the updated comment from our previous test.
change = CellChange(
    root_id=root,
    cell="E3",
    expected_value="Review illustration caption.",
    new_value="THIS MUST NEVER OVERWRITE HUMAN CONTENT",
)

print("=== PrOps V2 CONFLICT SAFETY TEST ===")
print("Existing E3:", original)

try:
    writer.apply([change], allow_writes=True)
except PMWriteConflict as error:
    print("EXPECTED CONFLICT DETECTED:", error)
else:
    raise AssertionError(
        "FAIL: Unsafe modification was not blocked"
    )

assert writer.read_cell("E3") == original
assert writer.read_cell("I2") == category_before

print("PASS: Existing comment preserved")
print("PASS: Manual category preserved")
print("PASS: No update sent to Google Sheets")
print("Production PM spreadsheet: UNCHANGED")
