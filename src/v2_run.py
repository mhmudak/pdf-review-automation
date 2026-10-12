from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend_cache import BackendSnapshot
from v2_backend import effective_author_rules
from v2_change_planner import (
    V2ChangePlan,
    plan_v2_changes,
)
from v2_model import (
    prepare_v2_entries,
    v2_author_summary,
)
from v2_mutations import (
    V2MutationSet,
    build_v2_mutations,
)
from v2_registry import (
    build_document_row,
    build_version_row,
)
from versioning import make_version_id


@dataclass(frozen=True)
class PreparedV2Run:
    document_key: str
    version_id: str
    entries: tuple[
        dict[str, Any],
        ...
    ]
    author_summary: dict[str, Any]
    change_plan: V2ChangePlan
    mutations: V2MutationSet
    document_row: dict[str, Any]
    version_row: dict[str, Any]


def prepare_v2_run(
    *,
    snapshot: BackendSnapshot,
    config: dict[str, Any],
    extracted_rows: list[
        dict[str, Any]
    ],
    summary: dict[str, Any],
    document_key: str,
    sha256: str,
    drive_file_id: str,
    pdf_name: str,
    drive_link: str,
    modified_time: str,
    size_bytes: Any,
    document_name: str = "",
    output_tab: str = "",
    master_version: str = "",
    historical_author_by_entry_id: (
        dict[str, str] | None
    ) = None,
    processed_at: str | None = None,
) -> PreparedV2Run:
    """
    Build the complete v2 decision package.

    Pure with respect to Google APIs:
    no reads, writes, Drive calls or notifications.
    """

    rules = effective_author_rules(
        snapshot,
        config,
    )

    entries = prepare_v2_entries(
        extracted_rows,
        document_key,
        sha256,
        author_rules=rules,
        historical_author_by_entry_id=(
            historical_author_by_entry_id
        ),
    )

    # Add file/version metadata needed by the
    # canonical sheet serializer.
    for entry in entries:
        entry["drive_file_id"] = (
            drive_file_id
        )
        entry["pdf_name"] = pdf_name
        entry["drive_link"] = drive_link
        entry["pdf_sha256"] = sha256

    author_summary = dict(
        v2_author_summary(
            entries
        )
    )

    # Stable outward contract for pipeline/reporting.
    # Keep whatever richer fields v2_author_summary()
    # already provides, while guaranteeing counts.
    author_summary.setdefault(
        "resolved_count",
        sum(
            1
            for entry in entries
            if str(
                entry.get(
                    "author_status",
                    "",
                )
            ).strip().upper()
            == "RESOLVED"
        ),
    )

    author_summary.setdefault(
        "unresolved_count",
        sum(
            1
            for entry in entries
            if str(
                entry.get(
                    "author_status",
                    "",
                )
            ).strip().upper()
            != "RESOLVED"
        ),
    )

    change_plan = plan_v2_changes(
        snapshot,
        document_key,
        entries,
    )

    mutations = build_v2_mutations(
        change_plan,
        recorded_at=processed_at,
    )

    document_row = build_document_row(
        document_key=document_key,
        document_name=(
            document_name
            or document_key
        ),
        output_tab=output_tab,
        master_version=master_version,
        sha256=sha256,
        drive_file_id=drive_file_id,
        modified_time=modified_time,
        entries=entries,
        processed_at=processed_at,
    )

    version_row = build_version_row(
        document_key=document_key,
        sha256=sha256,
        drive_file_id=drive_file_id,
        pdf_name=pdf_name,
        drive_link=drive_link,
        modified_time=modified_time,
        size_bytes=size_bytes,
        summary=summary,
        entries=entries,
        processed_at=processed_at,
    )

    return PreparedV2Run(
        document_key=document_key,
        version_id=make_version_id(
            document_key,
            sha256,
        ),
        entries=tuple(entries),
        author_summary=(
            author_summary
        ),
        change_plan=change_plan,
        mutations=mutations,
        document_row=document_row,
        version_row=version_row,
    )
