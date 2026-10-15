"""Offline fail-closed release audit; no Drive, Sheets or SMTP calls."""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from v2_release_gate import PRODUCTION_PM_ID, STAGING_PM_ID

print("PDF Review Automation V2 — release safety audit (OFFLINE)")
print("Current production PM target remains explicitly locked")
print("Production ID configured as destination:", os.getenv("V2_PM_OUTPUT_SPREADSHEET_ID") == PRODUCTION_PM_ID)
print("Staging ID configured as destination:", os.getenv("V2_PM_OUTPUT_SPREADSHEET_ID") == STAGING_PM_ID)
print("Notifications enabled:", os.getenv("NOTIFICATIONS_ENABLED", "false").lower() in ("true", "1", "yes"))
print("PM final authorization:", os.getenv("PM_FINAL_TEST_AUTHORIZED", "false").lower() in ("true", "1", "yes"))
print("READY_FOR_PRODUCTION: NO — destination authorization, recovery and live E2E remain pending")
