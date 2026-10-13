from __future__ import annotations

import json

from typing import Any

from versioning import entry_signature

from author_resolution import (
    AuthorResolution,
    AuthorRule,
    resolve_author,
)
from versioning import (
    make_version_id,
    normalize_document_key,
)


def prepare_v2_entries(
    extracted_rows: list[dict[str, Any]],
    document_key: str,
    sha256: str,
    author_rules: list[AuthorRule] | None = None,
    historical_author_by_entry_id: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """
    Convert extractor output into canonical v2 entries.

    This function is pure:
    - no Google Sheets
    - no Drive
    - no side effects
    """

    document_key = normalize_document_key(
        document_key
    )

    version_id = make_version_id(
        document_key,
        sha256,
    )

    author_rules = author_rules or []
    historical_author_by_entry_id = (
        historical_author_by_entry_id
        or {}
    )

    prepared: list[dict[str, Any]] = []

    seen_entry_ids: set[str] = set()

    for source in extracted_rows:
        entry_id = str(
            source.get("entry_id", "")
        ).strip()

        if not entry_id:
            raise ValueError(
                "extracted entry missing entry_id"
            )

        if entry_id in seen_entry_ids:
            raise ValueError(
                f"duplicate entry_id: {entry_id}"
            )

        seen_entry_ids.add(entry_id)

        candidate = dict(source)

        candidate["document_key"] = (
            document_key
        )

        candidate["version_id"] = (
            version_id
        )

        resolution: AuthorResolution = (
            resolve_author(
                candidate,
                author_rules,
                historical_author_by_entry_id,
            )
        )

        candidate["canonical_author"] = (
            resolution.canonical_author
        )

        candidate["author_status"] = (
            resolution.status
        )

        candidate[
            "author_resolution_method"
        ] = resolution.method

        candidate["author_rule_id"] = (
            resolution.rule_id
        )

        candidate["active"] = True
        candidate["source_state"] = (
            "CURRENT"
        )

        # Preserve native PDF annotation geometry for
        # deterministic page-position sorting.
        rect_fields = (
            "rect_x0", "rect_y0",
            "rect_x1", "rect_y1",
        )

        if all(
            candidate.get(field) is not None
            for field in rect_fields
        ):
            candidate["coordinates"] = json.dumps(
                {
                    field: float(candidate[field])
                    for field in rect_fields
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        else:
            candidate["coordinates"] = ""

        candidate["entry_signature"] = (
            entry_signature(candidate)
        )

        prepared.append(candidate)

    return prepared


def v2_author_summary(
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    resolved = [
        entry for entry in entries
        if entry.get("author_status") == "RESOLVED"
    ]
    unresolved = [
        entry for entry in entries
        if entry.get("author_status") != "RESOLVED"
    ]

    canonical_authors = sorted(
        {
            str(entry.get("canonical_author", "")).strip()
            for entry in resolved
            if str(entry.get("canonical_author", "")).strip()
        },
        key=str.casefold,
    )

    unresolved_raw_authors = sorted(
        {
            str(entry.get("raw_author", "")).strip()
            for entry in unresolved
            if str(entry.get("raw_author", "")).strip()
        },
        key=str.casefold,
    )

    return {
        "total": len(entries),
        "resolved": len(resolved),
        "unresolved": len(unresolved),
        "canonical_authors": canonical_authors,
        "unresolved_raw_authors": unresolved_raw_authors,
    }
