from __future__ import annotations

from typing import Any

from sheets_adapter import AUTHOR_REVIEW_HEADERS


def _text(value: Any) -> str:
    return str(value or "").strip()


def review_key(
    document_key: str,
    version_id: str,
    raw_author: str,
) -> str:
    return (
        f"{_text(document_key)}::"
        f"{_text(version_id)}::"
        f"{raw_author}"
    )


def build_author_review_rows(
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Aggregate unresolved entries into one PM-review row
    per (Document Key, Version ID, Raw Author).
    """

    groups: dict[
        tuple[str, str, str],
        list[dict[str, Any]],
    ] = {}

    for entry in entries:
        status = _text(
            entry.get("author_status")
        ).upper()

        if status == "RESOLVED":
            continue

        document_key = _text(
            entry.get("document_key")
        )

        version_id = _text(
            entry.get("version_id")
        )

        raw_author = str(
            entry.get("raw_author") or ""
        )

        key = (
            document_key,
            version_id,
            raw_author,
        )

        groups.setdefault(
            key,
            [],
        ).append(entry)

    rows = []

    for (
        document_key,
        version_id,
        raw_author,
    ), group in sorted(
        groups.items(),
        key=lambda item: item[0],
    ):
        sample_ids = []
        sample_pages = []
        sample_content = []

        for entry in group:
            entry_id = _text(
                entry.get("entry_id")
            )

            if (
                entry_id
                and entry_id not in sample_ids
                and len(sample_ids) < 5
            ):
                sample_ids.append(entry_id)

            page = _text(
                entry.get("book_page")
                or entry.get("pdf_page")
            )

            if (
                page
                and page not in sample_pages
                and len(sample_pages) < 8
            ):
                sample_pages.append(page)

            content = _text(
                entry.get("content")
                or entry.get("comment")
            )

            if (
                content
                and content not in sample_content
                and len(sample_content) < 3
            ):
                sample_content.append(
                    content[:160]
                )

        rows.append(
            {
                "Review Key": review_key(
                    document_key,
                    version_id,
                    raw_author,
                ),
                "Document Key":
                    document_key,
                "Version ID":
                    version_id,
                "Raw Author":
                    raw_author,
                "Entry Count":
                    len(group),
                "Sample Entry IDs":
                    ", ".join(sample_ids),
                "Sample Pages":
                    ", ".join(sample_pages),
                "Sample Content":
                    " | ".join(sample_content),
                "Suggested Canonical Author":
                    "",
                "Decision":
                    "",
                "Canonical Author":
                    "",
                "Rule Scope":
                    "VERSION",
                "Reviewed By":
                    "",
                "Reviewed At":
                    "",
                "Notes":
                    "",
            }
        )

    return rows


def dict_to_review_row(
    record: dict[str, Any],
) -> list[Any]:
    return [
        record.get(header, "")
        for header in AUTHOR_REVIEW_HEADERS
    ]


def upsert_author_review_rows(
    sheets: Any,
    review_rows: list[dict[str, Any]],
) -> dict[str, int]:
    """
    Insert missing review groups and refresh only the
    system-owned evidence columns for existing rows.

    PM-editable columns are preserved.
    """

    if not review_rows:
        return {
            "inserted": 0,
            "updated": 0,
        }

    existing_by_key = sheets.key_to_row(
        "_Author Review",
        key_col=0,
    )

    inserts = []
    updates = []

    for row in review_rows:
        key = _text(
            row.get("Review Key")
        )

        if not key:
            raise ValueError(
                "Author review row missing Review Key."
            )

        row_number = existing_by_key.get(
            key
        )

        if row_number is None:
            inserts.append(
                dict_to_review_row(row)
            )
            continue

        existing = sheets.get_row_values(
            "_Author Review",
            row_number,
        )

        # Preserve PM columns I:O.
        preserved = list(existing)

        while len(preserved) < len(
            AUTHOR_REVIEW_HEADERS
        ):
            preserved.append("")

        system_headers = [
            "Review Key",
            "Document Key",
            "Version ID",
            "Raw Author",
            "Entry Count",
            "Sample Entry IDs",
            "Sample Pages",
            "Sample Content",
        ]

        for header in system_headers:
            index = AUTHOR_REVIEW_HEADERS.index(
                header
            )

            preserved[index] = row.get(
                header,
                "",
            )

        updates.append(
            (
                row_number,
                preserved,
            )
        )

    if updates:
        sheets.batch_update_rows(
            "_Author Review",
            updates,
        )

    if inserts:
        sheets.append_rows(
            "_Author Review",
            inserts,
        )

    return {
        "inserted": len(inserts),
        "updated": len(updates),
    }


def approved_rules_from_review_values(
    values: list[list[Any]],
) -> list[dict[str, Any]]:
    """
    Convert explicit PM APPROVE decisions into VERSION
    author rules.

    No implicit approval.
    """

    if not values:
        return []

    headers = [
        _text(value)
        for value in values[0]
    ]

    index = {
        header: i
        for i, header in enumerate(headers)
    }

    required = {
        "Review Key",
        "Document Key",
        "Version ID",
        "Raw Author",
        "Decision",
        "Canonical Author",
        "Rule Scope",
        "Reviewed By",
        "Reviewed At",
        "Notes",
    }

    if not required.issubset(index):
        raise ValueError(
            "_Author Review headers are incomplete."
        )

    rules = []

    for row in values[1:]:
        def cell(name: str) -> str:
            i = index[name]
            return (
                _text(row[i])
                if i < len(row)
                else ""
            )

        if cell("Decision").upper() != "APPROVE":
            continue

        canonical = cell(
            "Canonical Author"
        )

        if not canonical:
            continue

        scope = (
            cell("Rule Scope").upper()
            or "VERSION"
        )

        if scope != "VERSION":
            raise ValueError(
                "Aggregated author-review approvals "
                "currently support VERSION scope only."
            )

        review_id = cell(
            "Review Key"
        )

        rules.append(
            {
                "Rule ID":
                    f"PM::{review_id}",
                "Scope":
                    "VERSION",
                "Document Key":
                    cell("Document Key"),
                "Version ID":
                    cell("Version ID"),
                "Root Entry ID":
                    "",
                "Entry ID":
                    "",
                "Raw Author":
                    cell("Raw Author"),
                "Canonical Author":
                    canonical,
                "Status":
                    "APPROVED",
                "Approved By":
                    cell("Reviewed By"),
                "Approved At":
                    cell("Reviewed At"),
                "Notes":
                    cell("Notes"),
            }
        )

    return rules
