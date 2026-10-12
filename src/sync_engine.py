from __future__ import annotations

import os

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sheets_adapter import (
    DATABASE_HEADERS,
    FILES_HEADERS,
    NEEDS_REVIEW_HEADERS,
    VISIBLE_HEADERS,
    SheetsAdapter,
)


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _client_timezone() -> ZoneInfo:
    timezone_name = os.getenv(
        "CLIENT_TIMEZONE",
        "Asia/Beirut",
    )

    try:
        return ZoneInfo(timezone_name)

    except Exception:
        # Safe fallback: never crash the workflow because
        # of a bad timezone configuration.
        return ZoneInfo("UTC")


def _now_client() -> str:
    return datetime.now(
        _client_timezone()
    ).isoformat()


def _coordinates(a: dict[str, Any]) -> str:
    return (
        f"{a['rect_x0']},"
        f"{a['rect_y0']},"
        f"{a['rect_x1']},"
        f"{a['rect_y1']}"
    )


def source_state(a: dict[str, Any]) -> str:
    if (
        not a.get("reviewer")
        or not a.get("book_page")
        or a.get("footer_status") == "footer_mismatch"
    ):
        return "NEEDS_REVIEW"

    return "CURRENT"


def database_row(
    a: dict[str, Any],
    drive_file_id: str,
    drive_link: str,
    first_seen: str,
    last_seen: str,
) -> list[Any]:
    return [
        a["identity_key"],
        a["reviewer"],
        a["raw_author"],
        a["source_file"],
        drive_file_id,
        drive_link,
        a["source_sha256"],
        a["pdf_page"],
        a["book_page"],
        a["mapping_method"],
        a["mapping_confidence"],
        a["annotation_type"],
        a.get("category", ""),
        a["comment"],
        a["selected_text"],
        a["created"],
        a["modified"],
        a["annotation_id"],
        a.get("reply_to_xref", ""),
        a["subject"],
        _coordinates(a),
        a["xref"],
        True,
        source_state(a),
        first_seen,
        last_seen,
    ]


def visible_row(
    a: dict[str, Any],
    drive_link: str,
) -> list[Any]:
    """
    Reviewer-facing canonical row.

    A  PDF Name
    B  PDF Drive Link
    C  Page
    D  Comment
    E  Category
    F  Author
    G  Created Date
    H  Last Modified
    I  Resolved?
    J  Replies
    K  Comment ID
    L  Annotation Type
    """
    return [
        a["source_file"],
        drive_link,
        a["book_page"],
        a["comment"],
        a.get("category", ""),
        a["reviewer"],
        a["created"],
        a["modified"],
        "",
        "",
        a.get("annotation_id")
        or a.get("identity_key", ""),
        a["annotation_type"],
    ]


def needs_review_row(
    a: dict[str, Any],
    drive_file_id: str,
) -> list[Any]:
    issues: list[str] = []

    if not a.get("reviewer"):
        issues.append(
            "REVIEWER_UNRESOLVED"
        )

    if not a.get("book_page"):
        issues.append(
            "PAGE_UNRESOLVED"
        )

    if (
        a.get("footer_status")
        == "footer_mismatch"
    ):
        issues.append(
            "PAGE_NUMBER_MISMATCH"
        )

    reason = (
        "; ".join(issues)
        or "REVIEW_REQUIRED"
    )

    return [
        _now_client(),
        drive_file_id,
        a["source_file"],
        reason,
        a.get("reviewer", ""),
        a.get("raw_author", ""),
        a.get("pdf_page", ""),
        (
            a.get(
                "footer_page_candidate",
                "",
            )
            or a.get(
                "book_page",
                "",
            )
        ),
        a.get("comment", ""),
        reason,
        "OPEN",
        "",
    ]


def _review_key(
    row: list[Any],
) -> tuple[str, str, str]:
    file_id = (
        str(row[1]).strip()
        if len(row) > 1
        else ""
    )

    pdf_page = (
        str(row[6]).strip()
        if len(row) > 6
        else ""
    )

    comment = (
        str(row[8]).strip()
        if len(row) > 8
        else ""
    )

    return (
        file_id,
        pdf_page,
        comment,
    )


# ============================================================
# REVIEWER OUTPUT SCHEMA + MIGRATION
# ============================================================


def _pad_row(
    row: list[Any],
    length: int,
) -> list[Any]:
    return [
        row[i]
        if i < len(row)
        else ""
        for i in range(length)
    ]


def _canonical_visible_header() -> list[str]:
    return list(
        VISIBLE_HEADERS
    )


def _legacy_eman_row(
    row: list[Any],
) -> list[Any]:
    """
    Legacy Eman layout:

    A PDF Name
    B Drive Link
    C Page
    D Comment
    E Author
    F Created
    G Modified
    H Resolved
    I Replies
    J Comment ID
    K Type

    The old K "Type" values are PDF annotation
    mechanics such as Highlight.

    Canonical layout:

    A PDF Name
    B PDF Drive Link
    C Page
    D Comment
    E Category
    F Author
    G Created Date
    H Last Modified
    I Resolved?
    J Replies
    K Comment ID
    L Annotation Type
    """
    r = _pad_row(
        row,
        11,
    )

    return [
        r[0],
        r[1],
        r[2],
        r[3],
        "",
        r[4],
        r[5],
        r[6],
        r[7],
        r[8],
        r[9],
        r[10],
    ]


def _legacy_annotation_type_e_row(
    row: list[Any],
) -> list[Any]:
    """
    Previous automation layout:

    E = Annotation Type
    F = Author
    ...
    K = Comment ID

    Move the PDF annotation type from E to L.
    Category remains empty.
    """
    r = _pad_row(
        row,
        11,
    )

    return [
        r[0],
        r[1],
        r[2],
        r[3],
        "",
        r[5],
        r[6],
        r[7],
        r[8],
        r[9],
        r[10],
        r[4],
    ]


def _truthy(
    value: Any,
) -> bool:
    if value is True:
        return True

    return (
        str(value)
        .strip()
        .lower()
        in {
            "1",
            "true",
            "yes",
            "y",
        }
    )


def _database_visible_row(
    row: list[Any],
) -> list[Any]:
    """
    Project one canonical _Database row to
    the reviewer-facing 12-column schema.
    """
    r = _pad_row(
        row,
        len(DATABASE_HEADERS),
    )

    annotation_key = str(
        r[0]
    ).strip()

    annotation_id = str(
        r[17]
    ).strip()

    sync_id = (
        annotation_id
        or annotation_key
    )

    return [
        r[3],   # PDF Name
        r[5],   # Drive Link
        r[8],   # Book Page
        r[13],  # Comment
        r[12],  # Category
        r[1],   # Reviewer
        r[15],  # Created
        r[16],  # Modified
        "",     # Resolved? preserved from output
        "",     # Replies preserved from output
        sync_id,
        r[11],  # Annotation Type
    ]


def _merge_visible_row(
    desired: list[Any],
    existing: list[Any],
) -> list[Any]:
    """
    Merge automation-controlled values with
    existing reviewer/PM-managed values.

    Preserve:
    - existing Category if backend Category is blank
    - Resolved?
    - Replies
    - existing Annotation Type if desired is blank
    """
    desired_row = _pad_row(
        desired,
        len(VISIBLE_HEADERS),
    )

    existing_row = _pad_row(
        existing,
        len(VISIBLE_HEADERS),
    )

    # Historical/manual Category survives when the
    # backend has no category value.
    if (
        not str(
            desired_row[4]
        ).strip()
        and str(
            existing_row[4]
        ).strip()
    ):
        desired_row[4] = (
            existing_row[4]
        )

    # PM/reviewer-managed fields.
    desired_row[8] = (
        existing_row[8]
    )

    desired_row[9] = (
        existing_row[9]
    )

    # Never erase an existing annotation type.
    if (
        not str(
            desired_row[11]
        ).strip()
        and str(
            existing_row[11]
        ).strip()
    ):
        desired_row[11] = (
            existing_row[11]
        )

    return desired_row


def normalize_reviewer_tab_schema(
    sheets: SheetsAdapter,
    sheet: str,
) -> str:
    """
    Normalize known historical reviewer-tab layouts
    to the canonical 12-column output schema.

    Unknown layouts fail closed instead of being
    guessed or rewritten.
    """
    values = (
        sheets.get_range_values(
            sheet,
            "A1:L",
        )
    )

    canonical = (
        _canonical_visible_header()
    )

    if not values:
        sheets.ensure_headers(
            sheet,
            canonical,
        )

        return "EMPTY_INITIALIZED"

    header = _pad_row(
        values[0],
        12,
    )

    # ---------------------------------------------------------
    # Already canonical
    # ---------------------------------------------------------
    if header[:12] == canonical:
        return "CANONICAL"

    # ---------------------------------------------------------
    # Previous automation schema
    #
    # E = Annotation Type
    # K = Comment ID
    # L absent
    # ---------------------------------------------------------
    if (
        header[0:4]
        == canonical[0:4]
        and header[4]
        == "Annotation Type"
        and header[5]
        == "Author"
        and header[10]
        == "Comment ID"
        and not str(
            header[11]
        ).strip()
    ):
        updates: list[
            tuple[
                int,
                list[Any],
            ]
        ] = []

        for (
            row_number,
            row,
        ) in enumerate(
            values[1:],
            start=2,
        ):
            if not row:
                continue

            updates.append(
                (
                    row_number,
                    _legacy_annotation_type_e_row(
                        row
                    ),
                )
            )

        sheets.batch_update_rows(
            sheet,
            updates,
        )

        sheets.ensure_headers(
            sheet,
            canonical,
        )

        return (
            "MIGRATED_"
            "ANNOTATION_TYPE_E"
        )

    # ---------------------------------------------------------
    # Luma historical layout
    #
    # E header = Type
    # E contains editorial categories such as:
    # Content / Instruction
    #
    # Positions are otherwise compatible.
    # ---------------------------------------------------------
    if (
        header[0:4]
        == canonical[0:4]
        and header[4]
        == "Type"
        and header[5]
        == "Author"
        and header[10]
        == "Comment ID"
        and not str(
            header[11]
        ).strip()
    ):
        sheets.ensure_headers(
            sheet,
            canonical,
        )

        return (
            "MIGRATED_"
            "CATEGORY_TYPE_HEADER"
        )

    # ---------------------------------------------------------
    # Osama historical layout
    #
    # E header blank
    # E contains category values such as Linguistic.
    # ---------------------------------------------------------
    if (
        header[0:4]
        == canonical[0:4]
        and not str(
            header[4]
        ).strip()
        and header[5]
        == "Author"
        and header[10]
        == "Comment ID"
        and not str(
            header[11]
        ).strip()
    ):
        sheets.ensure_headers(
            sheet,
            canonical,
        )

        return (
            "MIGRATED_"
            "CATEGORY_BLANK_HEADER"
        )

    # ---------------------------------------------------------
    # Eman historical layout
    #
    # E Author
    # J Comment ID
    # K Type = PDF annotation type
    # ---------------------------------------------------------
    if (
        header[0:4]
        == canonical[0:4]
        and header[4]
        == "Author"
        and header[9]
        == "Comment ID"
        and header[10]
        == "Type"
    ):
        updates: list[
            tuple[
                int,
                list[Any],
            ]
        ] = []

        for (
            row_number,
            row,
        ) in enumerate(
            values[1:],
            start=2,
        ):
            if not row:
                continue

            updates.append(
                (
                    row_number,
                    _legacy_eman_row(
                        row
                    ),
                )
            )

        sheets.batch_update_rows(
            sheet,
            updates,
        )

        sheets.ensure_headers(
            sheet,
            canonical,
        )

        return (
            "MIGRATED_"
            "EMAN_LEGACY"
        )

    # ---------------------------------------------------------
    # Hala historical layout
    #
    # E blank -> future Category
    # F Author
    # K Comment ID
    # L Type = Annotation Type
    #
    # Existing column positions are already correct.
    # Only normalize the headers.
    # ---------------------------------------------------------
    if (
        header[0:4]
        == canonical[0:4]
        and not str(
            header[4]
        ).strip()
        and header[5]
        == "Author"
        and header[10]
        == "Comment ID"
        and header[11]
        == "Type"
    ):
        sheets.ensure_headers(
            sheet,
            canonical,
        )

        return (
            "MIGRATED_"
            "HALA_LEGACY"
        )

    raise RuntimeError(
        "Unsupported reviewer-tab schema "
        f"for '{sheet}'. "
        "Refusing automatic migration."
    )


def _upsert_visible_rows(
    output_sheets: SheetsAdapter,
    tab_name: str,
    desired_rows: list[list[Any]],
) -> dict[str, Any]:
    """
    Shared output projection engine used by:
    - normal PDF processing
    - --reconcile-output

    Upsert key:
    K = Comment ID

    No automatic deletions.
    """
    output_sheets.ensure_sheet(
        tab_name
    )

    migration_status = (
        normalize_reviewer_tab_schema(
            output_sheets,
            tab_name,
        )
    )

    # Hide technical/audit columns:
    #
    # G:H = Created Date / Last Modified
    # K:L = Comment ID / Annotation Type
    output_sheets.hide_columns(
        tab_name,
        [
            (6, 8),
            (10, 12),
        ],
    )

    existing_values = (
        output_sheets.get_all_values(
            tab_name,
            refresh=True,
        )
    )

    existing_by_id: dict[
        str,
        tuple[
            int,
            list[Any],
        ],
    ] = {}

    for (
        row_number,
        existing,
    ) in enumerate(
        existing_values[1:],
        start=2,
    ):
        if len(existing) <= 10:
            continue

        existing_id = str(
            existing[10]
        ).strip()

        if existing_id:
            existing_by_id[
                existing_id
            ] = (
                row_number,
                existing,
            )

    append_rows: list[
        list[Any]
    ] = []

    updates: list[
        tuple[
            int,
            list[Any],
        ]
    ] = []

    pending_ids: set[str] = set()

    inserted = 0
    updated = 0
    unchanged = 0

    for desired in desired_rows:
        desired_row = _pad_row(
            desired,
            len(VISIBLE_HEADERS),
        )

        sync_id = str(
            desired_row[10]
        ).strip()

        if not sync_id:
            continue

        # Prevent duplicate appends inside the same run.
        if sync_id in pending_ids:
            continue

        existing_entry = (
            existing_by_id.get(
                sync_id
            )
        )

        if existing_entry is None:
            append_rows.append(
                desired_row
            )

            pending_ids.add(
                sync_id
            )

            inserted += 1

            continue

        (
            row_number,
            existing,
        ) = existing_entry

        merged = _merge_visible_row(
            desired_row,
            existing,
        )

        normalized_existing = (
            _pad_row(
                existing,
                len(VISIBLE_HEADERS),
            )
        )

        if (
            normalized_existing
            == merged
        ):
            unchanged += 1

        else:
            updates.append(
                (
                    row_number,
                    merged,
                )
            )

            updated += 1

    # One append call per reviewer tab.
    output_sheets.append_rows(
        tab_name,
        append_rows,
    )

    # One batch update per reviewer tab.
    output_sheets.batch_update_rows(
        tab_name,
        updates,
    )

    return {
        "migration": (
            migration_status
        ),
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
    }


# ============================================================
# BACKEND -> OUTPUT RECONCILIATION
# ============================================================


def reconcile_output_from_database(
    backend_sheets: SheetsAdapter,
    output_sheets: SheetsAdapter,
    reviewer_tab_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Rebuild/reconcile reviewer-facing tabs from
    canonical _Database records.

    This mode:
    - does not access Drive PDFs
    - does not modify _Files
    - does not modify _Database data
    - does not delete reviewer rows
    """
    reviewer_tab_map = (
        reviewer_tab_map
        or {}
    )

    backend_sheets.ensure_headers(
        "_Database",
        DATABASE_HEADERS,
    )

    db_rows = (
        backend_sheets
        .get_all_values(
            "_Database"
        )
    )

    by_reviewer: dict[
        str,
        list[list[Any]],
    ] = {}

    stats: dict[str, Any] = {
        "database_records": max(
            len(db_rows) - 1,
            0,
        ),
        "eligible_records": 0,
        "skipped_records": 0,
        "reviewers": 0,
        "inserted": 0,
        "updated": 0,
        "unchanged": 0,
        "tabs": {},
    }

    seen_keys: set[
        tuple[
            str,
            str,
        ]
    ] = set()

    for raw_row in db_rows[1:]:
        if not raw_row:
            continue

        row = _pad_row(
            raw_row,
            len(DATABASE_HEADERS),
        )

        reviewer = str(
            row[1]
        ).strip()

        active = _truthy(
            row[22]
        )

        source_state_value = (
            str(
                row[23]
            ).strip()
        )

        if (
            not reviewer
            or not active
            or source_state_value
            != "CURRENT"
        ):
            stats[
                "skipped_records"
            ] += 1

            continue

        visible = (
            _database_visible_row(
                row
            )
        )

        sync_id = str(
            visible[10]
        ).strip()

        if not sync_id:
            stats[
                "skipped_records"
            ] += 1

            continue

        dedup_key = (
            reviewer,
            sync_id,
        )

        if (
            dedup_key
            in seen_keys
        ):
            stats[
                "skipped_records"
            ] += 1

            continue

        seen_keys.add(
            dedup_key
        )

        by_reviewer.setdefault(
            reviewer,
            [],
        ).append(
            visible
        )

        stats[
            "eligible_records"
        ] += 1

    for (
        reviewer,
        desired_rows,
    ) in by_reviewer.items():
        tab_name = str(
            reviewer_tab_map.get(
                reviewer,
                reviewer,
            )
        ).strip()

        if not tab_name:
            raise RuntimeError(
                "Empty output tab name "
                f"for reviewer '{reviewer}'"
            )

        tab_stats = (
            _upsert_visible_rows(
                output_sheets,
                tab_name,
                desired_rows,
            )
        )

        stats["inserted"] += (
            tab_stats[
                "inserted"
            ]
        )

        stats["updated"] += (
            tab_stats[
                "updated"
            ]
        )

        stats["unchanged"] += (
            tab_stats[
                "unchanged"
            ]
        )

        stats["tabs"][
            tab_name
        ] = {
            "reviewer": reviewer,
            "eligible": len(
                desired_rows
            ),
            **tab_stats,
        }

    stats["reviewers"] = len(
        by_reviewer
    )

    return stats


# ============================================================
# NORMAL PDF INGESTION + SYNCHRONIZATION
# ============================================================


def sync_annotations(
    backend_sheets: SheetsAdapter,
    output_sheets: SheetsAdapter | None,
    annotations: list[dict[str, Any]],
    drive_file_id: str,
    drive_link: str,
    run_id: str,
    reviewer_tab_map: dict[str, str] | None = None,
) -> dict[str, int]:
    del run_id

    reviewer_tab_map = (
        reviewer_tab_map
        or {}
    )

    # ---------------------------------------------------------
    # BACKEND
    # ---------------------------------------------------------

    backend_sheets.ensure_headers(
        "_Database",
        DATABASE_HEADERS,
    )

    backend_sheets.ensure_headers(
        "_Needs Review",
        NEEDS_REVIEW_HEADERS,
    )

    db_rows = (
        backend_sheets
        .get_all_values(
            "_Database"
        )
    )

    existing: dict[
        str,
        tuple[
            int,
            list[Any],
        ],
    ] = {}

    for (
        row_number,
        row,
    ) in enumerate(
        db_rows[1:],
        start=2,
    ):
        if row:
            existing[
                str(row[0])
            ] = (
                row_number,
                row,
            )

    stats = {
        "inserted": 0,
        "updated": 0,
        "unchanged": 0,
        "skipped": 0,
        "needs_review": 0,
        "output_inserted": 0,
        "output_updated": 0,
        "output_unchanged": 0,
    }

    now = _now_utc()

    new_db_rows: list[
        list[Any]
    ] = []

    db_updates: list[
        tuple[
            int,
            list[Any],
        ]
    ] = []

    review_rows: list[
        list[Any]
    ] = []

    current_by_reviewer: dict[
        str,
        list[
            dict[str, Any]
        ],
    ] = {}

    seen_keys: set[str] = set()

    for a in annotations:
        if not a.get(
            "import_candidate",
            True,
        ):
            stats["skipped"] += 1
            continue

        key = a[
            "identity_key"
        ]

        if key in seen_keys:
            stats[
                "unchanged"
            ] += 1

            continue

        seen_keys.add(
            key
        )

        current = existing.get(
            key
        )

        first_seen = now

        if (
            current is not None
            and len(
                current[1]
            ) > 24
            and current[1][24]
        ):
            first_seen = str(
                current[1][24]
            )

        new_row = database_row(
            a,
            drive_file_id,
            drive_link,
            first_seen,
            now,
        )

        if current is None:
            new_db_rows.append(
                new_row
            )

            stats[
                "inserted"
            ] += 1

        else:
            (
                row_num,
                old,
            ) = current

            # Logical DB fields excluding
            # First Seen / Last Seen.
            compare_indexes = list(
                range(
                    0,
                    24,
                )
            )

            normalized_old = [
                old[i]
                if i < len(old)
                else ""
                for i
                in compare_indexes
            ]

            normalized_new = [
                new_row[i]
                for i
                in compare_indexes
            ]

            if (
                normalized_old
                != normalized_new
            ):
                db_updates.append(
                    (
                        row_num,
                        new_row,
                    )
                )

                stats[
                    "updated"
                ] += 1

            else:
                stats[
                    "unchanged"
                ] += 1

        state = source_state(
            a
        )

        if (
            state
            == "NEEDS_REVIEW"
        ):
            review_rows.append(
                needs_review_row(
                    a,
                    drive_file_id,
                )
            )

            stats[
                "needs_review"
            ] += 1

        else:
            reviewer = str(
                a.get(
                    "reviewer",
                    "",
                )
            ).strip()

            if reviewer:
                (
                    current_by_reviewer
                    .setdefault(
                        reviewer,
                        [],
                    )
                    .append(a)
                )

    # ---------------------------------------------------------
    # BACKEND BATCH WRITES
    # ---------------------------------------------------------

    backend_sheets.append_rows(
        "_Database",
        new_db_rows,
    )

    backend_sheets.batch_update_rows(
        "_Database",
        db_updates,
    )

    # ---------------------------------------------------------
    # NEEDS REVIEW
    # ---------------------------------------------------------

    if review_rows:
        existing_review = (
            backend_sheets
            .get_all_values(
                "_Needs Review"
            )
        )

        existing_review_keys = {
            _review_key(row)
            for row
            in existing_review[1:]
            if row
        }

        unique_review_rows = [
            row
            for row
            in review_rows
            if (
                _review_key(row)
                not in
                existing_review_keys
            )
        ]

        backend_sheets.append_rows(
            "_Needs Review",
            unique_review_rows,
        )

    # ---------------------------------------------------------
    # USER-FACING OUTPUT PROJECTION
    # ---------------------------------------------------------

    if output_sheets is None:
        return stats

    for (
        reviewer,
        reviewer_annotations,
    ) in current_by_reviewer.items():
        tab_name = str(
            reviewer_tab_map.get(
                reviewer,
                reviewer,
            )
        ).strip()

        if not tab_name:
            continue

        desired_rows = [
            visible_row(
                annotation,
                drive_link,
            )
            for annotation
            in reviewer_annotations
        ]

        tab_stats = (
            _upsert_visible_rows(
                output_sheets,
                tab_name,
                desired_rows,
            )
        )

        stats[
            "output_inserted"
        ] += tab_stats[
            "inserted"
        ]

        stats[
            "output_updated"
        ] += tab_stats[
            "updated"
        ]

        stats[
            "output_unchanged"
        ] += tab_stats[
            "unchanged"
        ]

    return stats


def files_registry_row(
    meta: dict[str, Any],
    summary: dict[str, Any],
    sync_stats: dict[str, int],
    status: str,
    error: str = "",
) -> list[Any]:
    message_parts: list[str] = []

    if (
        summary.get(
            "pages_mapped"
        )
        is not None
    ):
        message_parts.append(
            f"{summary.get('pages_mapped', 0)}/"
            f"{summary.get('pages', 0)} "
            "pages mapped"
        )

    skipped = sum(
        summary.get(
            "skipped_by_reason",
            {},
        ).values()
    )

    if skipped:
        message_parts.append(
            f"{skipped} "
            "empty annotations skipped"
        )

    if summary.get(
        "pages_unresolved"
    ):
        message_parts.append(
            f"{len(summary['pages_unresolved'])} "
            "unresolved pages"
        )

    if summary.get(
        "footer_mismatches"
    ):
        message_parts.append(
            f"{len(summary['footer_mismatches'])} "
            "footer mismatches"
        )

    if summary.get(
        "pages_beyond_master"
    ):
        message_parts.append(
            f"{summary['pages_beyond_master']} "
            "pages beyond master"
        )

    if summary.get(
        "master_mismatch_suspected"
    ):
        message_parts.append(
            "possible master-index mismatch"
        )

    if summary.get(
        "master_index_version"
    ):
        message_parts.append(
            "master="
            f"{summary['master_index_version']}"
        )

    if error:
        message_parts.append(
            error
        )

    return [
        meta.get(
            "file_id",
            "",
        ),
        meta.get(
            "name",
            "",
        ),
        meta.get(
            "web_view_link",
            "",
        ),
        meta.get(
            "modified_time",
            "",
        ),
        meta.get(
            "size",
            0,
        ),
        summary.get(
            "sha256",
            "",
        ),
        ", ".join(
            summary.get(
                "reviewers",
                [],
            )
        ),
        status,
        summary.get(
            "pages",
            0,
        ),
        summary.get(
            "annotations_found",
            0,
        ),
        sync_stats.get(
            "inserted",
            0,
        ),
        sync_stats.get(
            "updated",
            0,
        ),
        sync_stats.get(
            "unchanged",
            0,
        ),
        skipped,
        _now_client(),
        "; ".join(
            message_parts
        ),
    ]
