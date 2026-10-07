from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sheets_adapter import (
    DATABASE_HEADERS,
    FILES_HEADERS,
    NEEDS_REVIEW_HEADERS,
    VISIBLE_HEADERS,
    SheetsAdapter,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coordinates(a: dict[str, Any]) -> str:
    return f"{a['rect_x0']},{a['rect_y0']},{a['rect_x1']},{a['rect_y1']}"


def source_state(a: dict[str, Any]) -> str:
    if not a.get("reviewer") or not a.get("book_page") or a.get("footer_status") == "footer_mismatch":
        return "NEEDS_REVIEW"
    return "CURRENT"


def database_row(
    a: dict[str, Any], drive_file_id: str, drive_link: str, first_seen: str, last_seen: str
) -> list[Any]:
    return [
        a["identity_key"], a["reviewer"], a["raw_author"], a["source_file"], drive_file_id,
        drive_link, a["source_sha256"], a["pdf_page"], a["book_page"], a["mapping_method"],
        a["mapping_confidence"], a["annotation_type"], "", a["comment"], a["selected_text"],
        a["created"], a["modified"], a["annotation_id"], a.get("reply_to_xref", ""),
        a["subject"], _coordinates(a), a["xref"], True, source_state(a), first_seen, last_seen,
    ]


def visible_row(a: dict[str, Any], drive_link: str) -> list[Any]:
    return [
        a["source_file"], drive_link, a["book_page"], a["comment"], a["annotation_type"],
        a["reviewer"], a["created"], a["modified"], "", "", a["annotation_id"],
    ]


def needs_review_row(a: dict[str, Any], drive_file_id: str) -> list[Any]:
    issues: list[str] = []
    if not a.get("reviewer"):
        issues.append("REVIEWER_UNRESOLVED")
    if not a.get("book_page"):
        issues.append("PAGE_UNRESOLVED")
    if a.get("footer_status") == "footer_mismatch":
        issues.append("PAGE_NUMBER_MISMATCH")
    reason = "; ".join(issues) or "REVIEW_REQUIRED"
    return [
        _now(), drive_file_id, a["source_file"], reason,
        a.get("reviewer", ""), a.get("raw_author", ""), a.get("pdf_page", ""),
        a.get("footer_page_candidate", "") or a.get("book_page", ""),
        a.get("comment", ""), reason, "OPEN", "",
    ]


def sync_annotations(
    sheets: SheetsAdapter,
    annotations: list[dict[str, Any]],
    drive_file_id: str,
    drive_link: str,
    run_id: str,
) -> dict[str, int]:
    del run_id  # retained in function signature for compatibility; timestamps now provide audit history.
    sheets.ensure_headers("_Database", DATABASE_HEADERS)
    sheets.ensure_headers("_Needs Review", NEEDS_REVIEW_HEADERS)
    db_rows = sheets.get_all_values("_Database")
    existing: dict[str, tuple[int, list[Any]]] = {}
    for i, row in enumerate(db_rows[1:], start=2):
        if row:
            existing[str(row[0])] = (i, row)

    stats = {"inserted": 0, "updated": 0, "unchanged": 0, "skipped": 0, "needs_review": 0}
    reviewer_new: dict[str, list[list[Any]]] = {}
    review_rows: list[list[Any]] = []
    now = _now()

    for a in annotations:
        if not a.get("import_candidate", True):
            stats["skipped"] += 1
            continue

        key = a["identity_key"]
        current = existing.get(key)
        first_seen = now
        if current is not None and len(current[1]) > 24 and current[1][24]:
            first_seen = str(current[1][24])
        new_row = database_row(a, drive_file_id, drive_link, first_seen, now)

        if current is None:
            sheets.append_rows("_Database", [new_row])
            stats["inserted"] += 1
        else:
            row_num, old = current
            # Compare all logical fields except First Seen / Last Seen.
            compare_indexes = list(range(0, 24))
            normalized_old = [old[i] if i < len(old) else "" for i in compare_indexes]
            normalized_new = [new_row[i] for i in compare_indexes]
            sheets.update_row("_Database", row_num, new_row)
            if normalized_old != normalized_new:
                stats["updated"] += 1
            else:
                stats["unchanged"] += 1

        if source_state(a) == "NEEDS_REVIEW":
            review_rows.append(needs_review_row(a, drive_file_id))
            stats["needs_review"] += 1
        elif current is None:
            reviewer_new.setdefault(a["reviewer"], []).append(visible_row(a, drive_link))

    if review_rows:
        sheets.append_rows("_Needs Review", review_rows)

    for reviewer, rows in reviewer_new.items():
        sheets.ensure_headers(reviewer, VISIBLE_HEADERS)
        sheets.append_rows(reviewer, rows)
    return stats


def files_registry_row(
    meta: dict[str, Any], summary: dict[str, Any], sync_stats: dict[str, int], status: str, error: str = ""
) -> list[Any]:
    message_parts: list[str] = []
    if summary.get("pages_mapped") is not None:
        message_parts.append(f"{summary.get('pages_mapped', 0)}/{summary.get('pages', 0)} pages mapped")
    skipped = sum(summary.get("skipped_by_reason", {}).values())
    if skipped:
        message_parts.append(f"{skipped} empty annotations skipped")
    if summary.get("pages_unresolved"):
        message_parts.append(f"{len(summary['pages_unresolved'])} unresolved pages")
    if summary.get("footer_mismatches"):
        message_parts.append(f"{len(summary['footer_mismatches'])} footer mismatches")
    if error:
        message_parts.append(error)

    return [
        meta.get("file_id", ""), meta.get("name", ""), meta.get("web_view_link", ""),
        meta.get("modified_time", ""), meta.get("size", 0), summary.get("sha256", ""),
        ", ".join(summary.get("reviewers", [])), status, summary.get("pages", 0),
        summary.get("annotations_found", 0), sync_stats.get("inserted", 0),
        sync_stats.get("updated", 0), sync_stats.get("unchanged", 0), skipped,
        _now(), "; ".join(message_parts),
    ]
