"""Durable notification bridge for V2 pipeline alerts.

No automatic retries of uncertain SMTP delivery.
No email or Sheets access when notifications are disabled.
"""

import os

from notifier import (
    notification_mode,
    notifications_enabled,
    send_email,
)
from v2_notification_policy import event_key
from v2_notification_dispatcher import dispatch_notification


def dispatch_pipeline_alert(
    *,
    alert,
    file_meta,
    sheets,
    status,
    verified_export_required,
    summary=None,
    export_result=None,
    error="",
    sender=None,
):
    """Dispatch one V2 alert with a stable event identity."""

    if not notifications_enabled():
        return {"action": "NOTIFICATIONS_DISABLED", "sent": False}

    status = str(status).upper()
    if status not in {"PROCESSED", "ERROR"}:
        raise ValueError("UNSUPPORTED_PIPELINE_NOTIFICATION_STATUS")

    if status == "PROCESSED":
        proof = export_result or {}

        if (
            verified_export_required is not True
            or not isinstance(proof, dict)
            or proof.get("verified") is not True
            or not str(proof.get("export_id") or "").strip()
        ):
            return {
                "action": "UNVERIFIED_V2_SUCCESS_BLOCKED",
                "sent": False,
            }

    if sheets is None:
        raise RuntimeError("NOTIFICATION_LEDGER_UNAVAILABLE")

    summary = summary or {}
    file_id = str(file_meta.file_id)
    modified = str(file_meta.modified_time)
    size = str(file_meta.size)
    digest = str(summary.get("sha256") or "")
    code = str(alert.get("code") or status)

    # A repeated Scheduler run must not create a new email.
    # A changed Drive observation or changed failure can create
    # a different event, subject to the normal verification rules.
    export_id = (
        str(export_result["export_id"]).strip()
        if status == "PROCESSED" else ""
    )

    event_identity = "\x1f".join((
        file_id, modified, size, digest, status, code,
        export_id,
        str(error) if status == "ERROR" else "",
    ))

    key = event_key(
        file_id,
        "PIPELINE_" + status + "_" + code,
        event_identity,
    )

    audiences = [
        str(value).upper()
        for value in alert.get("audience", [])
    ]

    if status == "ERROR":
        audience = ["ADMIN"]
    elif "PM" in audiences:
        audience = ["PM"]
    elif "ADMIN" in audiences:
        audience = ["ADMIN"]
    else:
        # Do not invent a notification recipient.
        return {"action": "NO_ALERT_AUDIENCE", "sent": False}

    mode = notification_mode()

    intent = {
        "notify": True,
        "key": key,
        "kind": "PIPELINE_" + status + "_" + code,
        "audience": audience,
        "severity": str(alert.get("severity") or "INFO"),
        "document_key": file_id,
        "message": (
            "PDF: " + str(file_meta.name) + "\n\n"
            + str(alert.get("message") or "")
            + ("\n\nError: " + str(error) if error else "")
        ),
    }

    return dispatch_notification(
        sheets=sheets,
        intent=intent,
        mode=mode,
        admin_email=os.getenv("ADMIN_EMAIL", ""),
        pm_email=os.getenv("PM_EMAIL", ""),
        pm_final_test_authorized=(
            os.getenv("PM_FINAL_TEST_AUTHORIZED", "")
            .strip().lower() in {"1", "true", "yes"}
        ),
        send_email_fn=sender or send_email,
        allow_writes=True,
    )


def verified_completion_fallback(alerts, route_result):
    """Return a PM confirmation only if none already exists.

    Never infer export success from configuration alone.
    Does not send mail or modify Sheets.
    """
    result = route_result or {}
    proof = result.get("pm_export_result") or {}

    if (
        not isinstance(proof, dict)
        or proof.get("verified") is not True
        or not str(proof.get("export_id") or "").strip()
    ):
        return None

    for alert in alerts or []:
        audience = [
            str(item).strip().upper()
            for item in alert.get("audience", [])
        ]
        if "PM" in audience:
            return None

    return {
        "code": "PDF_EXPORT_VERIFIED",
        "severity": "INFO",
        "audience": ["PM"],
        "pm_actionable": False,
        "message": (
            "The PDF was processed successfully. "
            "Its review results were verified in the "
            "designated PM spreadsheet. "
            "Export ID: " + str(proof["export_id"])
        ),
    }


def verified_identical_upload_ack(
    *,
    file_id,
    sha256,
    previous_file,
    matching_file,
    route_result,
):
    """Build acknowledgment only for a distinct known-content Drive file."""
    proof = (route_result or {}).get("pm_export_result")

    if (
        previous_file is not None
        or matching_file is None
        or str(matching_file.file_id) == str(file_id)
        or str(matching_file.sha256).lower() != str(sha256).lower()
        or str(getattr(matching_file, "status", "")).upper()
            not in {"PROCESSED", "DUPLICATE"}
        or not isinstance(proof, dict)
        or proof.get("verified") is not True
        or not str(proof.get("export_id") or "").strip()
    ):
        return None

    return {
        "code": "IDENTICAL_UPLOAD_ACKNOWLEDGED",
        "severity": "INFO",
        "audience": ["PM"],
        "message": (
            "A new PDF file was received and checked. "
            "Its content matches a previously recorded version. "
            "The corresponding PM export was verified; "
            "existing review results remain available. "
            "Export ID: " + str(proof["export_id"])
        ),
    }
