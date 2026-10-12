from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sheets_adapter import (
    DOCUMENT_HEADERS,
    VERSION_HEADERS,
    SheetsAdapter,
)
from versioning import make_version_id


def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def unresolved_author_count(
    entries: list[dict[str, Any]],
) -> int:
    return sum(
        1
        for entry in entries
        if str(
            entry.get(
                "author_status",
                "",
            )
        ).strip().upper()
        != "RESOLVED"
    )


def version_status(
    entries: list[dict[str, Any]],
) -> str:
    if unresolved_author_count(entries):
        return "NEEDS_AUTHOR_REVIEW"

    return "PROCESSED"


def build_version_row(
    *,
    document_key: str,
    sha256: str,
    drive_file_id: str,
    pdf_name: str,
    drive_link: str,
    modified_time: str,
    size_bytes: Any,
    summary: dict[str, Any],
    entries: list[dict[str, Any]],
    processed_at: str | None = None,
    message: str = "",
) -> dict[str, Any]:
    processed_at = (
        processed_at
        or utc_now()
    )

    version_id = make_version_id(
        document_key,
        sha256,
    )

    raw_authors = sorted(
        {
            str(
                entry.get(
                    "raw_author",
                    "",
                )
            ).strip()
            for entry in entries
            if str(
                entry.get(
                    "raw_author",
                    "",
                )
            ).strip()
        }
    )

    return {
        "Version ID": version_id,
        "Document Key": document_key,
        "Drive File ID": drive_file_id,
        "PDF Name": pdf_name,
        "Drive Link": drive_link,
        "Modified Time": modified_time,
        "Size Bytes": size_bytes,
        "PDF SHA256": sha256,
        "Version Status": version_status(
            entries
        ),
        "Authors Found": ", ".join(
            raw_authors
        ),
        "Pages": summary.get(
            "pages",
            "",
        ),
        "Entries Found": summary.get(
            "entries_found",
            len(entries),
        ),
        "Root Comments": summary.get(
            "comments_found",
            summary.get(
                "root_relations",
                "",
            ),
        ),
        "Replies": summary.get(
            "replies_found",
            summary.get(
                "reply_relations",
                "",
            ),
        ),
        "Processed At": processed_at,
        "Message / Error": message,
    }


def build_document_row(
    *,
    document_key: str,
    document_name: str,
    output_tab: str,
    master_version: str,
    sha256: str,
    drive_file_id: str,
    modified_time: str,
    entries: list[dict[str, Any]],
    processed_at: str | None = None,
) -> dict[str, Any]:
    processed_at = (
        processed_at
        or utc_now()
    )

    return {
        "Document Key": document_key,
        "Document Name": (
            document_name
            or document_key
        ),
        "Output Tab": output_tab,
        "Master Version": master_version,
        "Current Version ID": (
            make_version_id(
                document_key,
                sha256,
            )
        ),
        "Current Drive File ID": (
            drive_file_id
        ),
        "Current PDF SHA256": sha256,
        "Current Modified Time": (
            modified_time
        ),
        "Status": version_status(
            entries
        ),
        "Last Processed": processed_at,
    }


def row_from_dict(
    record: dict[str, Any],
    headers: list[str],
) -> list[Any]:
    return [
        record.get(
            header,
            "",
        )
        for header in headers
    ]


def apply_v2_registry(
    sheets: SheetsAdapter,
    *,
    document_row: dict[str, Any],
    version_row: dict[str, Any],
) -> dict[str, int]:
    """
    Persist current document state and immutable
    version metadata.

    Rules:
    - _Documents has one row per Document Key.
    - _Versions has one row per Version ID.
    - Existing Version ID is never duplicated.
    - Validation happens before any write.
    """

    document_key = str(
        document_row.get(
            "Document Key",
            "",
        )
    ).strip()

    version_id = str(
        version_row.get(
            "Version ID",
            "",
        )
    ).strip()

    if not document_key:
        raise ValueError(
            "Document row missing Document Key."
        )

    if not version_id:
        raise ValueError(
            "Version row missing Version ID."
        )

    if (
        str(
            version_row.get(
                "Document Key",
                "",
            )
        ).strip()
        != document_key
    ):
        raise ValueError(
            "Document/Version key mismatch."
        )

    document_rows = sheets.key_to_row(
        "_Documents",
        key_col=0,
    )

    version_rows = sheets.key_to_row(
        "_Versions",
        key_col=0,
    )

    document_row_number = (
        document_rows.get(
            document_key
        )
    )

    version_row_number = (
        version_rows.get(
            version_id
        )
    )

    # Existing version IDs are immutable.
    # Verify that they still belong to this document.
    if version_row_number is not None:
        existing_values = (
            sheets.get_row_values(
                "_Versions",
                version_row_number,
            )
        )

        existing_document_key = (
            str(
                existing_values[1]
                if len(existing_values) > 1
                else ""
            ).strip()
        )

        existing_sha = (
            str(
                existing_values[7]
                if len(existing_values) > 7
                else ""
            ).strip().lower()
        )

        incoming_sha = str(
            version_row.get(
                "PDF SHA256",
                "",
            )
        ).strip().lower()

        if (
            existing_document_key
            != document_key
            or existing_sha
            != incoming_sha
        ):
            raise ValueError(
                "Existing Version ID conflicts "
                "with incoming version metadata."
            )

    # All validation finished.
    # Writes start below.

    document_inserted = 0
    document_updated = 0
    version_inserted = 0

    serialized_document = row_from_dict(
        document_row,
        DOCUMENT_HEADERS,
    )

    if document_row_number is None:
        sheets.append_rows(
            "_Documents",
            [
                serialized_document
            ],
        )

        document_inserted = 1

    else:
        sheets.batch_update_rows(
            "_Documents",
            [
                (
                    document_row_number,
                    serialized_document,
                )
            ],
        )

        document_updated = 1

    if version_row_number is None:
        sheets.append_rows(
            "_Versions",
            [
                row_from_dict(
                    version_row,
                    VERSION_HEADERS,
                )
            ],
        )

        version_inserted = 1

    return {
        "document_inserted":
            document_inserted,
        "document_updated":
            document_updated,
        "version_inserted":
            version_inserted,
        "version_existing":
            int(
                version_row_number
                is not None
            ),
    }
