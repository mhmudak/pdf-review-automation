from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from v2_change_planner import V2ChangePlan


@dataclass(frozen=True)
class V2MutationSet:
    insert_entries: tuple[dict[str, Any], ...]
    update_entries: tuple[dict[str, Any], ...]
    deactivate_entries: tuple[dict[str, Any], ...]
    history_rows: tuple[dict[str, Any], ...]

    def counts(self) -> dict[str, int]:
        return {
            "INSERT": len(self.insert_entries),
            "UPDATE": len(self.update_entries),
            "DEACTIVATE": len(self.deactivate_entries),
            "HISTORY": len(self.history_rows),
        }


def _now_utc() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def _entry_key(
    document_key: str,
    entry_id: str,
) -> str:
    return f"{document_key}::{entry_id}"


def _value(
    row: dict[str, Any],
    key: str,
    default: Any = "",
) -> Any:
    return row.get(
        key,
        default,
    )


def _canonical_entry(
    document_key: str,
    current: dict[str, Any],
    *,
    first_seen: str,
    last_seen: str,
) -> dict[str, Any]:
    entry_id = str(
        current["entry_id"]
    ).strip()

    return {
        "Entry Key": _entry_key(
            document_key,
            entry_id,
        ),
        "Document Key": document_key,
        "Version ID": _value(
            current,
            "version_id",
        ),
        "Drive File ID": _value(
            current,
            "drive_file_id",
        ),
        "PDF Name": _value(
            current,
            "pdf_name",
            _value(
                current,
                "source_file",
            ),
        ),
        "Drive Link": _value(
            current,
            "drive_link",
        ),
        "PDF SHA256": _value(
            current,
            "pdf_sha256",
            _value(
                current,
                "source_sha256",
            ),
        ),
        "Entry ID": entry_id,
        "Entry Signature": _value(
            current,
            "entry_signature",
        ),
        "Parent Entry ID": _value(
            current,
            "parent_entry_id",
        ),
        "Root Entry ID": _value(
            current,
            "root_entry_id",
        ),
        "Entry Type": _value(
            current,
            "entry_type",
        ),
        "Reply Depth": _value(
            current,
            "reply_depth",
        ),
        "Raw Author": _value(
            current,
            "raw_author",
        ),
        "Canonical Author": _value(
            current,
            "canonical_author",
        ),
        "Author Status": _value(
            current,
            "author_status",
        ),
        "Author Resolution Method": _value(
            current,
            "author_resolution_method",
        ),
        "Author Rule ID": _value(
            current,
            "author_rule_id",
        ),
        "PDF Page": _value(
            current,
            "pdf_page",
        ),
        "Book Page": _value(
            current,
            "book_page",
        ),
        "Page Mapping Method": _value(
            current,
            "mapping_method",
            _value(
                current,
                "page_mapping_method",
            ),
        ),
        "Page Mapping Confidence": _value(
            current,
            "mapping_confidence",
            _value(
                current,
                "page_mapping_confidence",
            ),
        ),
        "Annotation Type": _value(
            current,
            "annotation_type",
        ),
        "Relation Type": _value(
            current,
            "relation_type",
        ),
        "Category": _value(
            current,
            "category",
        ),
        "Content": _value(
            current,
            "comment",
            _value(
                current,
                "content",
            ),
        ),
        "Selected Text": _value(
            current,
            "selected_text",
        ),
        "Created Date": _value(
            current,
            "created",
            _value(
                current,
                "created_date",
            ),
        ),
        "Modified Date": _value(
            current,
            "modified",
            _value(
                current,
                "modified_date",
            ),
        ),
        "Coordinates": _value(
            current,
            "coordinates",
        ),
        "XRef": _value(
            current,
            "xref",
        ),
        "Active": True,
        "Source State": "CURRENT",
        "First Seen": first_seen,
        "Last Seen": last_seen,
    }


def _history_row(
    *,
    change_type: str,
    document_key: str,
    current: dict[str, Any] | None,
    previous: dict[str, Any] | None,
    recorded_at: str,
) -> dict[str, Any]:
    source = current or previous or {}

    entry_id = str(
        _value(
            source,
            "entry_id",
            _value(
                source,
                "Entry ID",
            ),
        )
    ).strip()

    version_id = _value(
        current or {},
        "version_id",
        _value(
            previous or {},
            "Version ID",
        ),
    )

    signature = _value(
        current or {},
        "entry_signature",
        _value(
            previous or {},
            "Entry Signature",
        ),
    )

    previous_signature = _value(
        previous or {},
        "Entry Signature",
    )

    return {
        "History Key": (
            f"{document_key}::"
            f"{entry_id}::"
            f"{version_id}::"
            f"{change_type}"
        ),
        "Document Key": document_key,
        "Version ID": version_id,
        "Drive File ID": _value(
            current or {},
            "drive_file_id",
            _value(
                previous or {},
                "Drive File ID",
            ),
        ),
        "PDF SHA256": _value(
            current or {},
            "pdf_sha256",
            _value(
                current or {},
                "source_sha256",
                _value(
                    previous or {},
                    "PDF SHA256",
                ),
            ),
        ),
        "Entry ID": entry_id,
        "Entry Signature": signature,
        "Change Type": change_type,
        "Previous Signature": previous_signature,
        "Raw Author": _value(
            current or {},
            "raw_author",
            _value(
                previous or {},
                "Raw Author",
            ),
        ),
        "Canonical Author": _value(
            current or {},
            "canonical_author",
            _value(
                previous or {},
                "Canonical Author",
            ),
        ),
        "Author Status": _value(
            current or {},
            "author_status",
            _value(
                previous or {},
                "Author Status",
            ),
        ),
        "Parent Entry ID": _value(
            current or {},
            "parent_entry_id",
            _value(
                previous or {},
                "Parent Entry ID",
            ),
        ),
        "Root Entry ID": _value(
            current or {},
            "root_entry_id",
            _value(
                previous or {},
                "Root Entry ID",
            ),
        ),
        "Entry Type": _value(
            current or {},
            "entry_type",
            _value(
                previous or {},
                "Entry Type",
            ),
        ),
        "Reply Depth": _value(
            current or {},
            "reply_depth",
            _value(
                previous or {},
                "Reply Depth",
            ),
        ),
        "PDF Page": _value(
            current or {},
            "pdf_page",
            _value(
                previous or {},
                "PDF Page",
            ),
        ),
        "Book Page": _value(
            current or {},
            "book_page",
            _value(
                previous or {},
                "Book Page",
            ),
        ),
        "Annotation Type": _value(
            current or {},
            "annotation_type",
            _value(
                previous or {},
                "Annotation Type",
            ),
        ),
        "Relation Type": _value(
            current or {},
            "relation_type",
            _value(
                previous or {},
                "Relation Type",
            ),
        ),
        "Category": _value(
            current or {},
            "category",
            _value(
                previous or {},
                "Category",
            ),
        ),
        "Content": _value(
            current or {},
            "comment",
            _value(
                current or {},
                "content",
                _value(
                    previous or {},
                    "Content",
                ),
            ),
        ),
        "Selected Text": _value(
            current or {},
            "selected_text",
            _value(
                previous or {},
                "Selected Text",
            ),
        ),
        "Created Date": _value(
            current or {},
            "created",
            _value(
                previous or {},
                "Created Date",
            ),
        ),
        "Modified Date": _value(
            current or {},
            "modified",
            _value(
                previous or {},
                "Modified Date",
            ),
        ),
        "Coordinates": _value(
            current or {},
            "coordinates",
            _value(
                previous or {},
                "Coordinates",
            ),
        ),
        "XRef": _value(
            current or {},
            "xref",
            _value(
                previous or {},
                "XRef",
            ),
        ),
        "Active": (
            change_type != "REMOVED"
        ),
        "Source State": (
            "HISTORICAL"
            if change_type == "REMOVED"
            else "CURRENT"
        ),
        "Recorded At": recorded_at,
    }


def build_v2_mutations(
    plan: V2ChangePlan,
    *,
    recorded_at: str | None = None,
) -> V2MutationSet:
    """
    Convert a pure change plan into minimal backend
    mutations.

    UNCHANGED entries intentionally generate no writes.
    """

    now = recorded_at or _now_utc()

    inserts: list[
        dict[str, Any]
    ] = []

    updates: list[
        dict[str, Any]
    ] = []

    deactivations: list[
        dict[str, Any]
    ] = []

    history: list[
        dict[str, Any]
    ] = []

    for change in plan.changes:
        if change.change_type == "UNCHANGED":
            continue

        if change.change_type == "NEW":
            assert change.current is not None

            canonical = _canonical_entry(
                plan.document_key,
                change.current,
                first_seen=now,
                last_seen=now,
            )

            inserts.append(
                canonical
            )

            history.append(
                _history_row(
                    change_type="NEW",
                    document_key=plan.document_key,
                    current=change.current,
                    previous=None,
                    recorded_at=now,
                )
            )

            continue

        if change.change_type in {
            "UPDATED",
            "AUTHOR_UPDATED",
        }:
            assert change.current is not None
            assert change.previous is not None

            first_seen = str(
                change.previous.get(
                    "First Seen",
                    "",
                )
            ).strip() or now

            canonical = _canonical_entry(
                plan.document_key,
                change.current,
                first_seen=first_seen,
                last_seen=now,
            )

            # Preserve human-assigned categories when the
            # newly extracted PDF supplies no category.
            new_category = str(
                canonical.get("Category") or ""
            ).strip()

            if not new_category:
                canonical["Category"] = change.previous.get(
                    "Category", ""
                )

            updates.append(
                canonical
            )

            history.append(
                _history_row(
                    change_type=change.change_type,
                    document_key=plan.document_key,
                    current=change.current,
                    previous=change.previous,
                    recorded_at=now,
                )
            )

            continue

        if change.change_type == "REMOVED":
            assert change.previous is not None

            deactivated = dict(
                change.previous
            )

            deactivated[
                "Active"
            ] = False

            deactivated[
                "Source State"
            ] = "HISTORICAL"

            deactivated[
                "Last Seen"
            ] = now

            deactivations.append(
                deactivated
            )

            history.append(
                _history_row(
                    change_type="REMOVED",
                    document_key=plan.document_key,
                    current=None,
                    previous=change.previous,
                    recorded_at=now,
                )
            )

            continue

        raise ValueError(
            "Unsupported change type: "
            f"{change.change_type}"
        )

    return V2MutationSet(
        insert_entries=tuple(inserts),
        update_entries=tuple(updates),
        deactivate_entries=tuple(deactivations),
        history_rows=tuple(history),
    )
