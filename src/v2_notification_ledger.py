"""Durable V2 notification attempts.

No SMTP calls. No automatic tab creation.
A single authorized worker is required: Sheets is not atomic CAS.
"""

from datetime import datetime, timezone

TAB = "_Notifications_V2"

HEADERS = [
    "Event Key",
    "Document Key",
    "Event Kind",
    "Recipient",
    "State",
    "Created At UTC",
    "Updated At UTC",
    "Error",
]

STATES = {
    "PENDING",
    "SENDING",
    "SENT",
    "DELIVERY_UNCERTAIN",
}


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def _required(value, name):
    value = str(value or "").strip()
    if not value:
        raise ValueError(name + " is required")
    return value


def _rows(sheets):
    values = sheets.get_all_values(TAB, refresh=True)

    if not values or list(values[0]) != HEADERS:
        raise RuntimeError("NOTIFICATION_LEDGER_SCHEMA_MISMATCH")

    indexed = {}
    for number, raw in enumerate(values[1:], start=2):
        row = (list(raw) + [""] * len(HEADERS))[:len(HEADERS)]
        key = row[0].strip()
        if not key or key in indexed or row[4] not in STATES:
            raise RuntimeError("NOTIFICATION_LEDGER_INTEGRITY_ERROR")
        indexed[key] = (number, row)

    return indexed


def get_notification(sheets, key):
    key = _required(key, "event_key")
    entry = _rows(sheets).get(key)
    if entry is None:
        return None
    number, row = entry
    return {"row_number": number, **dict(zip(HEADERS, row))}


def create_pending(
    sheets, *, key, document_key, kind, recipient,
    allow_writes=False,
):
    """Create event once. Existing events are never reset."""
    key = _required(key, "event_key")
    document_key = _required(document_key, "document_key")
    kind = _required(kind, "kind")
    recipient = _required(recipient, "recipient")

    existing = get_notification(sheets, key)
    if existing:
        if (
            existing["Document Key"] != document_key
            or existing["Event Kind"] != kind
            or existing["Recipient"] != recipient
        ):
            raise RuntimeError("NOTIFICATION_EVENT_IDENTITY_CONFLICT")
        return existing

    if not allow_writes:
        return {"State": "NOT_PERSISTED", "Event Key": key}

    timestamp = now_utc()
    row = [
        key, document_key, kind, recipient,
        "PENDING", timestamp, timestamp, "",
    ]

    # Best-effort race detection, not an atomic lock.
    if get_notification(sheets, key) is not None:
        raise RuntimeError("CONCURRENT_NOTIFICATION_INSERT")

    sheets.append_rows(TAB, [row])
    stored = get_notification(sheets, key)

    if stored is None or stored["State"] != "PENDING":
        raise RuntimeError("NOTIFICATION_INTENT_NOT_VERIFIED")

    return stored


def transition(
    sheets, *, key, expected_state, new_state,
    error="", allow_writes=False,
):
    """Read-back verified state transition; no automatic resend."""
    allowed = {
        ("PENDING", "SENDING"),
        ("SENDING", "SENT"),
        ("SENDING", "DELIVERY_UNCERTAIN"),
    }

    if (expected_state, new_state) not in allowed:
        raise ValueError("INVALID_NOTIFICATION_TRANSITION")

    existing = get_notification(sheets, key)

    if existing is None:
        raise RuntimeError("NOTIFICATION_EVENT_NOT_FOUND")

    if existing["State"] != expected_state:
        raise RuntimeError("NOTIFICATION_STATE_CONFLICT")

    if not allow_writes:
        return {"State": existing["State"], "written": False}

    # Verify the current state before committing the transition.
    latest = get_notification(sheets, key)
    if latest != existing:
        raise RuntimeError("NOTIFICATION_CHANGED_CONCURRENTLY")

    updated = [
        existing["Event Key"],
        existing["Document Key"],
        existing["Event Kind"],
        existing["Recipient"],
        new_state,
        existing["Created At UTC"],
        now_utc(),
        str(error),
    ]

    sheets.batch_update_rows(
        TAB, [(existing["row_number"], updated)]
    )

    stored = get_notification(sheets, key)
    if stored is None or stored["State"] != new_state:
        raise RuntimeError("NOTIFICATION_TRANSITION_UNVERIFIED")

    return {**stored, "written": True}


def delivery_decision(record):
    """Only never-attempted events can begin SMTP delivery."""
    if record is None:
        return "NO_EVENT"

    state = record["State"]

    return {
        "PENDING": "ATTEMPT_ALLOWED",
        "SENDING": "MANUAL_RECONCILIATION",
        "SENT": "NOOP_ALREADY_SENT",
        "DELIVERY_UNCERTAIN": "MANUAL_RECONCILIATION",
        "NOT_PERSISTED": "BLOCK_UNPERSISTED",
    }[state]
