"""Checkpoint-backed notification dispatch.

The calling pipeline must run with a single authorized worker.
Google Sheets state transitions are not atomic CAS operations.
No automatic retry after SMTP delivery begins.
"""

from v2_notification_policy import delivery_plan
from v2_notification_ledger import (
    create_pending,
    delivery_decision,
    get_notification,
    transition,
)


def dispatch_notification(
    *,
    sheets,
    intent,
    mode,
    admin_email="",
    pm_email="",
    pm_final_test_authorized=False,
    send_email_fn=None,
    allow_writes=False,
):
    """Dispatch at most one SMTP attempt per persisted event key.

    The sender is injected to permit completely offline tests.
    A SENDING record left after a crash is never retried here.
    """
    if not intent.get("notify"):
        return {"action": "NO_EVENT", "sent": False}

    plan = delivery_plan(
        intent,
        mode=mode,
        admin_email=admin_email,
        pm_email=pm_email,
        pm_final_test_authorized=pm_final_test_authorized,
    )

    if not plan.get("send"):
        return {
            "action": plan.get("reason", "DISABLED"),
            "sent": False,
        }

    if not allow_writes:
        return {
            "action": "DRY_RUN",
            "sent": False,
            "recipients": plan["recipients"],
            "event_key": plan["key"],
        }

    if send_email_fn is None:
        raise RuntimeError("NOTIFICATION_SENDER_NOT_CONFIGURED")

    recipients = plan["recipients"]
    if len(recipients) != 1:
        raise RuntimeError("ONE_RECIPIENT_REQUIRED")

    key = plan["key"]
    record = create_pending(
        sheets,
        key=key,
        document_key=intent["document_key"],
        kind=intent["kind"],
        recipient=recipients[0],
        allow_writes=True,
    )

    decision = delivery_decision(record)

    if decision == "NOOP_ALREADY_SENT":
        return {
            "action": "ALREADY_SENT",
            "sent": False,
            "event_key": key,
        }

    if decision == "MANUAL_RECONCILIATION":
        return {
            "action": "DELIVERY_REVIEW_REQUIRED",
            "sent": False,
            "event_key": key,
            "state": record["State"],
        }

    if decision != "ATTEMPT_ALLOWED":
        raise RuntimeError("NOTIFICATION_NOT_READY_FOR_DELIVERY")

    # Durable write and readback must succeed BEFORE SMTP begins.
    transition(
        sheets,
        key=key,
        expected_state="PENDING",
        new_state="SENDING",
        allow_writes=True,
    )

    confirmed = get_notification(sheets, key)
    if not confirmed or confirmed["State"] != "SENDING":
        raise RuntimeError("NOTIFICATION_SENDING_NOT_PERSISTED")

    subject = (
        plan.get("subject_prefix", "")
        + "[PDF Review]["
        + intent["severity"]
        + "] "
        + intent["document_key"]
        + " - "
        + intent["kind"]
    )

    body = (
        "PDF Review Automation\n\n"
        + intent["message"]
        + "\n\nEvent ID: "
        + key
    )

    try:
        send_email_fn(recipients, subject, body)
    except Exception as exc:
        # A transport exception cannot prove that the server
        # did not accept the email. Do not retry automatically.
        try:
            transition(
                sheets,
                key=key,
                expected_state="SENDING",
                new_state="DELIVERY_UNCERTAIN",
                error=type(exc).__name__ + ": " + str(exc),
                allow_writes=True,
            )
        except Exception:
            # SENDING itself blocks future retries.
            # Preserve the original SMTP exception.
            pass
        raise RuntimeError(
            "NOTIFICATION_DELIVERY_UNCERTAIN: " + key
        ) from exc

    # If this write fails after SMTP succeeds, the durable
    # SENDING record prevents an automatic duplicate email.
    transition(
        sheets,
        key=key,
        expected_state="SENDING",
        new_state="SENT",
        allow_writes=True,
    )

    return {
        "action": "SENT",
        "sent": True,
        "event_key": key,
        "recipients": recipients,
    }
