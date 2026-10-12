from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class VersionDecision:
    action: str
    version_id: str
    reason: str


@dataclass(frozen=True)
class EntryChange:
    entry_id: str
    state: str
    previous: dict[str, Any] | None
    current: dict[str, Any] | None


def normalize_document_key(value: Any) -> str:
    """
    Stable logical-document key normalization.
    This is NOT derived from reviewer or Drive file ID.
    """
    return "_".join(
        str(value or "")
        .strip()
        .upper()
        .replace("-", "_")
        .split()
    )


def make_version_id(
    document_key: str,
    sha256: str,
) -> str:
    """
    Deterministic version identity.

    Full SHA is retained internally so two binaries cannot
    collide merely because they share a short hash prefix.
    """
    document_key = normalize_document_key(
        document_key
    )

    sha256 = str(
        sha256 or ""
    ).strip().lower()

    if not document_key:
        raise ValueError(
            "document_key is required"
        )

    if len(sha256) != 64:
        raise ValueError(
            "sha256 must be a full 64-character digest"
        )

    return f"{document_key}@{sha256}"


def classify_version(
    document_key: str,
    sha256: str,
    known_sha256: set[str],
) -> VersionDecision:
    """
    Same binary SHA for the same logical document:
    DUPLICATE.

    Different SHA:
    NEW_VERSION.
    """
    normalized_known = {
        str(value or "").strip().lower()
        for value in known_sha256
        if str(value or "").strip()
    }

    version_id = make_version_id(
        document_key,
        sha256,
    )

    normalized_sha = str(
        sha256
    ).strip().lower()

    if normalized_sha in normalized_known:
        return VersionDecision(
            action="DUPLICATE",
            version_id=version_id,
            reason="SHA256_ALREADY_KNOWN",
        )

    return VersionDecision(
        action="NEW_VERSION",
        version_id=version_id,
        reason="SHA256_NOT_SEEN_FOR_DOCUMENT",
    )


def _stable_value(value: Any) -> Any:
    """
    Make values deterministic before hashing.
    """
    if isinstance(value, dict):
        return {
            str(k): _stable_value(v)
            for k, v in sorted(
                value.items(),
                key=lambda item: str(item[0]),
            )
        }

    if isinstance(value, list):
        return [
            _stable_value(v)
            for v in value
        ]

    if value is None:
        return ""

    return value


# Fields that define the semantic/native state of an entry.
#
# Deliberately excluded:
# - version_id
# - Drive File ID/link
# - PDF SHA
# - Canonical Author
# - Author resolution metadata
# - First Seen / Last Seen
#
# A PM correcting "User" -> "Faten Khalifeh" must NOT make
# the PDF annotation look modified.
ENTRY_COMPARE_FIELDS = (
    "raw_author",
    "pdf_page",
    "book_page",
    "annotation_type",
    "relation_type",
    "parent_entry_id",
    "root_entry_id",
    "reply_depth",
    "comment",
    "selected_text",
    "subject",
    "created",
    "modified",
    "rect_x0",
    "rect_y0",
    "rect_x1",
    "rect_y1",
)


def entry_signature(
    entry: dict[str, Any],
) -> str:
    payload = {
        field: _stable_value(
            entry.get(field, "")
        )
        for field in ENTRY_COMPARE_FIELDS
    }

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(
        encoded
    ).hexdigest()


def compare_versions(
    previous_entries: list[dict[str, Any]],
    current_entries: list[dict[str, Any]],
) -> list[EntryChange]:
    """
    Compare two authoritative versions of one logical PDF.

    Native entry_id is the primary identity.

    Results:
      NEW
      UPDATED
      UNCHANGED
      REMOVED

    REMOVED means absent from the new authoritative version.
    It must later become Active=False / HISTORICAL.
    """

    previous_by_id: dict[str, dict[str, Any]] = {}
    current_by_id: dict[str, dict[str, Any]] = {}

    for entry in previous_entries:
        entry_id = str(
            entry.get("entry_id", "")
        ).strip()

        if not entry_id:
            raise ValueError(
                "previous entry missing entry_id"
            )

        if entry_id in previous_by_id:
            raise ValueError(
                f"duplicate previous entry_id: {entry_id}"
            )

        previous_by_id[entry_id] = entry

    for entry in current_entries:
        entry_id = str(
            entry.get("entry_id", "")
        ).strip()

        if not entry_id:
            raise ValueError(
                "current entry missing entry_id"
            )

        if entry_id in current_by_id:
            raise ValueError(
                f"duplicate current entry_id: {entry_id}"
            )

        current_by_id[entry_id] = entry

    changes: list[EntryChange] = []

    all_ids = sorted(
        set(previous_by_id)
        | set(current_by_id)
    )

    for entry_id in all_ids:
        old = previous_by_id.get(
            entry_id
        )

        new = current_by_id.get(
            entry_id
        )

        if old is None:
            changes.append(
                EntryChange(
                    entry_id=entry_id,
                    state="NEW",
                    previous=None,
                    current=new,
                )
            )
            continue

        if new is None:
            changes.append(
                EntryChange(
                    entry_id=entry_id,
                    state="REMOVED",
                    previous=old,
                    current=None,
                )
            )
            continue

        if (
            entry_signature(old)
            == entry_signature(new)
        ):
            state = "UNCHANGED"
        else:
            state = "UPDATED"

        changes.append(
            EntryChange(
                entry_id=entry_id,
                state=state,
                previous=old,
                current=new,
            )
        )

    return changes


def change_counts(
    changes: list[EntryChange],
) -> dict[str, int]:
    counts = {
        "NEW": 0,
        "UPDATED": 0,
        "UNCHANGED": 0,
        "REMOVED": 0,
    }

    for change in changes:
        if change.state not in counts:
            raise ValueError(
                f"unknown change state: {change.state}"
            )

        counts[change.state] += 1

    return counts
