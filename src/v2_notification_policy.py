"""Notification policy for PDF Review Automation V2.

Pure decision logic: no Google Sheets writes, SMTP or network calls.

A delivery dispatcher must separately persist a unique event key
and a delivery-attempt record before sending any email.
"""

from hashlib import sha256


MODES = {"OFF", "TEST", "FINAL", "PRODUCTION"}


def event_key(document_key, event_kind, event_id):
    """Stable identity for one document event, not one scheduler run."""
    parts = [str(x).strip() for x in (
        document_key, event_kind, event_id
    )]
    if not all(parts):
        raise ValueError("Notification event identity is incomplete")
    return sha256(
        "\x1f".join(parts).encode("utf-8")
    ).hexdigest()


def decide_notification(
    *,
    event_kind,
    document_key,
    event_id="",
    export_verified=False,
    export_id="",
    error="",
):
    """Return a notification intent or an explicit NOOP.

    Event kinds:
      SCHEDULED_NO_CHANGE: no newly detected file event
      IDENTICAL_UPLOAD: genuine new upload, identical PDF bytes
      EXPORT_COMPLETED: changed PDF, verified PM destination
      REVIEW_REQUIRED: verified export requiring human review
      EXPORT_FAILED: processing or verification failure

    Caller must independently establish that an upload is new.
    """

    kind = str(event_kind).strip().upper()

    if kind == "SCHEDULED_NO_CHANGE":
        return {"notify": False, "reason": "NO_NEW_UPLOAD"}

    supported = {
        "IDENTICAL_UPLOAD",
        "EXPORT_COMPLETED",
        "REVIEW_REQUIRED",
        "EXPORT_FAILED",
    }
    if kind not in supported:
        raise ValueError("Unknown notification event kind")

    if kind in {"EXPORT_COMPLETED", "REVIEW_REQUIRED"}:
        if not export_verified or not str(export_id).strip():
            raise ValueError(
                "PM notification requires a verified export ID"
            )

    if kind == "EXPORT_FAILED" and not str(error).strip():
        raise ValueError("Failure alert requires an error")

    identity = event_id
    if kind in {"EXPORT_COMPLETED", "REVIEW_REQUIRED"}:
        identity = export_id

    key = event_key(document_key, kind, identity)

    messages = {
        "IDENTICAL_UPLOAD": (
            "The uploaded PDF was checked. Its content matches "
            "the previously processed version. Existing review "
            "results remain valid; no reprocessing was necessary."
        ),
        "EXPORT_COMPLETED": (
            "The updated PDF was processed and the review "
            "destination was successfully verified."
        ),
        "REVIEW_REQUIRED": (
            "The updated PDF was processed and verified. "
            "Some items require manual review."
        ),
        "EXPORT_FAILED": (
            "PDF processing or output verification failed. "
            "Administrator intervention is required."
        ),
    }

    return {
        "notify": True,
        "key": key,
        "kind": kind,
        "audience": (
            ["ADMIN"] if kind == "EXPORT_FAILED" else ["PM"]
        ),
        "severity": (
            "ERROR" if kind == "EXPORT_FAILED"
            else "ACTION" if kind == "REVIEW_REQUIRED"
            else "INFO"
        ),
        "message": (
            messages[kind]
            + (" Error: " + str(error) if kind == "EXPORT_FAILED" else "")
        ),
        "document_key": str(document_key),
    }


def delivery_plan(
    intent,
    *,
    mode,
    admin_email="",
    pm_email="",
    pm_final_test_authorized=False,
):
    """Resolve recipients without ever sending an email."""

    mode = str(mode).strip().upper()
    if mode not in MODES:
        raise ValueError("Invalid notification mode")

    if not intent.get("notify"):
        return {"send": False, "reason": "NO_EVENT"}

    if mode == "OFF":
        return {"send": False, "reason": "MODE_OFF"}

    if mode == "TEST":
        recipient = str(admin_email).strip()
        if not recipient:
            raise RuntimeError("ADMIN_EMAIL_REQUIRED_FOR_TEST")
        return {
            "send": True,
            "recipients": [recipient],
            "subject_prefix": "[TEST]",
            "key": intent["key"],
        }

    if mode == "FINAL" and pm_final_test_authorized is not True:
        raise RuntimeError("PM_FINAL_TEST_NOT_AUTHORIZED")

    recipient_name = intent["audience"][0]
    recipient = (
        str(admin_email).strip()
        if recipient_name == "ADMIN"
        else str(pm_email).strip()
    )
    if not recipient:
        raise RuntimeError(
            recipient_name + "_EMAIL_NOT_CONFIGURED"
        )

    return {
        "send": True,
        "recipients": [recipient],
        "subject_prefix": (
            "[FINAL TEST]" if mode == "FINAL" else ""
        ),
        "key": intent["key"],
    }
