"""Explicit administrator-only SMTP integration test.

Default: offline dry run.
--send-admin-test: writes one event to backend notification
ledger and attempts exactly one email to ADMIN_EMAIL.

Never writes to the PM spreadsheet.
"""

import argparse
import os
import sys
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "src")
)

from notifier import (
    notification_mode,
    notifications_enabled,
    send_email,
)
from sheets_adapter import SheetsAdapter
from v2_notification_policy import event_key
from v2_notification_dispatcher import dispatch_notification

BACKEND_ID = "1DXZJsEG1993iEkzBNJWDAZYhFc2AC2Fm29DTjdYFWIg"


def make_test_intent(test_id):
    return {
        "notify": True,
        "key": event_key("SYSTEM_TEST", "SMTP_TEST", test_id),
        "kind": "SMTP_TEST",
        "audience": ["ADMIN"],
        "severity": "INFO",
        "document_key": "SYSTEM_TEST",
        "message": (
            "This is an administrator-only delivery test.\n"
            "No PDF was uploaded or processed.\n"
            "No PM spreadsheet was modified.\n"
            "No action is required."
        ),
    }


def main(send):
    load_dotenv()

    admin = os.getenv("ADMIN_EMAIL", "").strip()

    print("=== ADMIN EMAIL DELIVERY TEST ===")
    print("Destination: administrator only")
    print("Send requested:", send)
    print("Production PM writes: DISABLED")

    # The actual event is unique each time an explicit test
    # is requested. A scheduler rerun will not call this script.
    test_id = uuid4().hex
    intent = make_test_intent(test_id)

    if not send:
        result = dispatch_notification(
            sheets=None,
            intent=intent,
            mode="TEST",
            admin_email=admin or "dry-run@example.invalid",
            allow_writes=False,
        )
        print("Action:", result["action"])
        print("Email attempts: 0")
        print("Google Sheets writes: 0")
        return

    if notification_mode() != "TEST":
        raise RuntimeError(
            "NOTIFICATION_MODE_MUST_BE_TEST"
        )

    if not notifications_enabled():
        raise RuntimeError(
            "NOTIFICATIONS_ENABLED_MUST_BE_TRUE"
        )

    required = (
        "ADMIN_EMAIL",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
    )

    missing = [
        name for name in required
        if not os.getenv(name, "").strip()
    ]
    if missing:
        raise RuntimeError(
            "MISSING_EMAIL_CONFIGURATION: "
            + ", ".join(missing)
        )

    # Check basic SMTP configuration before writing an
    # event that would otherwise become delivery-uncertain.
    port = int(os.getenv("SMTP_PORT", "465"))
    if port not in (465, 587):
        raise RuntimeError("UNSUPPORTED_SMTP_PORT")

    backend = SheetsAdapter(BACKEND_ID)

    result = dispatch_notification(
        sheets=backend,
        intent=intent,
        mode="TEST",
        admin_email=admin,
        pm_email="",
        send_email_fn=send_email,
        allow_writes=True,
    )

    print("Action:", result["action"])
    print("Event key:", result["event_key"])
    print("Recipient:", admin)
    print("PM notifications: DISABLED")
    print("PM spreadsheet writes: 0")

    if result["action"] != "SENT":
        raise RuntimeError("ADMIN_TEST_NOT_CONFIRMED")

    print("PASS: Administrator email accepted by SMTP")
    print("PASS: Notification delivery state persisted")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--send-admin-test",
        action="store_true",
        help="Explicitly authorize one live test email",
    )
    arguments = parser.parse_args()
    main(arguments.send_admin_test)
