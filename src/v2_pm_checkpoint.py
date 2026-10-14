"""Pure lifecycle model for recoverable PrOps V2 PM exports.

No Google calls, writes, emails or deployment operations.
Persistence and source snapshots will be integrated separately.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from typing import Any


STATES = frozenset({
    "EXPORT_PENDING",
    "EXPORTING",
    "EXPORT_VERIFIED",
    "NOTIFICATION_PENDING",
    "COMPLETED",
    "DELIVERY_UNCERTAIN",
})


def _required(value: Any, label: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"{label} is required")
    return result


def new_export_checkpoint(
    *,
    document_key: str,
    version_id: str,
    pdf_sha256: str,
    output_spreadsheet_id: str,
    output_tab: str,
    previous_exported_version_id: str = "",
) -> dict[str, Any]:
    """Create deterministic identity for one destination/version."""

    document = _required(document_key, "document_key")
    version = _required(version_id, "version_id")
    destination = _required(
        output_spreadsheet_id, "output_spreadsheet_id"
    )
    tab = _required(output_tab, "output_tab")
    digest = _required(pdf_sha256, "pdf_sha256").lower()

    if len(digest) != 64 or any(
        c not in "0123456789abcdef" for c in digest
    ):
        raise ValueError("pdf_sha256 must contain 64 hex characters")

    identity = "\x1f".join([
        document, version, digest, destination, tab,
    ])

    export_id = sha256(identity.encode("utf-8")).hexdigest()

    previous = str(previous_exported_version_id or "").strip()
    if previous == version:
        raise ValueError(
            "Previous successfully exported version cannot "
            "be the pending version"
        )

    return {
        "export_id": export_id,
        "document_key": document,
        "version_id": version,
        "pdf_sha256": digest,
        "output_spreadsheet_id": destination,
        "output_tab": tab,
        "previous_exported_version_id": previous,
        "state": "EXPORT_PENDING",
        "attempts": 0,
        "verified_projection_digest": "",
        "error": "",
        "notification_key": export_id,
    }


def advance_checkpoint(
    checkpoint: dict[str, Any],
    event: str,
    *,
    verification_digest: str = "",
    error: str = "",
) -> dict[str, Any]:
    """Validate one state transition without mutating the input.

    The caller must independently verify sheet content before
    supplying EXPORT_VERIFIED and its projection digest.
    """
    current = deepcopy(checkpoint)
    state = current.get("state")

    if state not in STATES:
        raise ValueError(f"Unknown export state: {state!r}")

    allowed = {
        ("EXPORT_PENDING", "START_EXPORT"): "EXPORTING",
        ("EXPORTING", "EXPORT_FAILED"): "EXPORT_PENDING",
        ("EXPORTING", "EXPORT_VERIFIED"): "EXPORT_VERIFIED",
        ("EXPORT_VERIFIED", "QUEUE_NOTIFICATION"):
            "NOTIFICATION_PENDING",
        ("EXPORT_VERIFIED", "COMPLETE_WITHOUT_NOTIFICATION"):
            "COMPLETED",
        ("NOTIFICATION_PENDING", "CONFIRM_DELIVERY"):
            "COMPLETED",
        ("NOTIFICATION_PENDING", "DELIVERY_UNCERTAIN"):
            "DELIVERY_UNCERTAIN",
    }

    key = (state, event)
    if key not in allowed:
        raise ValueError(
            f"Illegal checkpoint transition: {state} + {event}"
        )

    if event == "EXPORT_VERIFIED":
        digest = str(verification_digest).strip().lower()
        if len(digest) != 64 or any(
            c not in "0123456789abcdef" for c in digest
        ):
            raise ValueError(
                "Verified export requires a 64-character "
                "projection digest"
            )
        current["verified_projection_digest"] = digest

    if event == "START_EXPORT":
        current["attempts"] += 1
        current["error"] = ""

    if event == "EXPORT_FAILED":
        current["error"] = str(error or "Export failed")

    current["state"] = allowed[key]
    return current


def recover_after_interruption(
    checkpoint: dict[str, Any],
) -> dict[str, Any]:
    """Return safe next action after an interrupted operation."""
    state = checkpoint.get("state")

    actions = {
        "EXPORT_PENDING": "VERIFY_DESTINATION_THEN_RESUME",
        "EXPORTING": "VERIFY_DESTINATION_THEN_RESUME",
        "EXPORT_VERIFIED": "RESOLVE_NOTIFICATION_POLICY",
        "NOTIFICATION_PENDING": "CHECK_DELIVERY_BEFORE_RETRY",
        "COMPLETED": "NO_ACTION",
        "DELIVERY_UNCERTAIN": "MANUAL_DELIVERY_REVIEW",
    }

    if state not in actions:
        raise ValueError(f"Unknown state: {state!r}")

    return {
        "export_id": checkpoint["export_id"],
        "state": state,
        "next_action": actions[state],
    }
