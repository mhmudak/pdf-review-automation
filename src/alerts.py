from __future__ import annotations

from typing import Any


SEVERITIES = {
    "INFO",
    "WARNING",
    "ERROR",
    "CRITICAL",
}


def classify_pdf_result(
    file_name: str,
    summary: dict[str, Any],
    sync_stats: dict[str, int],
    status: str = "PROCESSED",
    error: str = "",
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []

    if status == "ERROR":
        alerts.append(
            {
                "severity": "ERROR",
                "audience": ["ADMIN", "PM"],
                "code": "PDF_PROCESSING_ERROR",
                "file": file_name,
                "message": error or "PDF processing failed.",
                "pm_actionable": True,
            }
        )

        return alerts

    inserted = int(sync_stats.get("inserted", 0) or 0)
    updated = int(sync_stats.get("updated", 0) or 0)
    unchanged = int(sync_stats.get("unchanged", 0) or 0)

    reviewers = summary.get("reviewers", [])
    reviewer_name = (
        reviewers[0]
        if len(reviewers) == 1
        else ", ".join(reviewers)
    )

    alerts.append(
        {
            "severity": "INFO",
            "audience": ["ADMIN", "PM"],
            "code": "PDF_PROCESSED",
            "file": file_name,
            "message": (
                f"{file_name} processed successfully; "
                f"reviewer={reviewer_name or 'unresolved'}; "
                f"new={inserted}; "
                f"updated={updated}; "
                f"unchanged={unchanged}."
            ),
            "pm_actionable": False,
        }
    )

    if not reviewers:
        alerts.append(
            {
                "severity": "WARNING",
                "audience": ["ADMIN", "PM"],
                "code": "REVIEWER_UNRESOLVED",
                "file": file_name,
                "message": (
                    "Reviewer could not be resolved. "
                    "Manual reviewer assignment may be required."
                ),
                "pm_actionable": True,
            }
        )

    unresolved_pages = summary.get(
        "pages_unresolved",
        [],
    )

    if unresolved_pages:
        alerts.append(
            {
                "severity": "WARNING",
                "audience": ["ADMIN", "PM"],
                "code": "PAGE_MAPPING_UNRESOLVED",
                "file": file_name,
                "message": (
                    f"{len(unresolved_pages)} page(s) "
                    "could not be mapped automatically."
                ),
                "pm_actionable": True,
            }
        )

    footer_mismatches = summary.get(
        "footer_mismatches",
        [],
    )

    if footer_mismatches:
        alerts.append(
            {
                "severity": "WARNING",
                "audience": ["ADMIN"],
                "code": "PAGE_NUMBER_MISMATCH",
                "file": file_name,
                "message": (
                    f"{len(footer_mismatches)} page-number "
                    "mismatch(es) detected."
                ),
                "pm_actionable": False,
            }
        )

    if summary.get(
        "master_mismatch_suspected"
    ):
        alerts.append(
            {
                "severity": "WARNING",
                "audience": ["ADMIN"],
                "code": "MASTER_INDEX_MISMATCH",
                "file": file_name,
                "message": (
                    "Possible master-index mismatch detected; "
                    f"coverage="
                    f"{summary.get('mapping_coverage', 0):.1%}; "
                    f"master="
                    f"{summary.get('master_index_version', '')}."
                ),
                "pm_actionable": False,
            }
        )

    if summary.get("pages_beyond_master", 0):
        alerts.append(
            {
                "severity": "INFO",
                "audience": ["ADMIN"],
                "code": "PAGES_BEYOND_MASTER",
                "file": file_name,
                "message": (
                    f"{summary.get('pages_beyond_master', 0)} "
                    "page(s) exceed the current master page count."
                ),
                "pm_actionable": False,
            }
        )

    needs_review_count = int(
        sync_stats.get(
            "needs_review",
            0,
        )
        or 0
    )

    if needs_review_count:
        alerts.append(
            {
                "severity": "WARNING",
                "audience": ["ADMIN", "PM"],
                "code": "NEEDS_REVIEW",
                "file": file_name,
                "message": (
                    f"{needs_review_count} annotation(s) "
                    "require manual review."
                ),
                "pm_actionable": True,
            }
        )

    return alerts