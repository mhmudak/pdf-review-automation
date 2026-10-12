from __future__ import annotations

from backend_cache import (
    BackendSnapshot,
    snapshot_from_batch_values,
)
from sheets_adapter import (
    AUTHOR_RULE_HEADERS,
    DOCUMENT_HEADERS,
    ENTRY_HISTORY_HEADERS,
    ENTRY_V2_HEADERS,
    VERSION_HEADERS,
    SheetsAdapter,
)


V2_SNAPSHOT_SHEETS = [
    "_Documents",
    "_Versions",
    "_Entries_V2",
    "_Author Rules",
]


def ensure_v2_backend(
    sheets: SheetsAdapter,
) -> None:
    """
    Explicit setup/migration operation.

    This should not run on every idle scheduler poll.
    """

    schemas = [
        (
            "_Documents",
            DOCUMENT_HEADERS,
        ),
        (
            "_Versions",
            VERSION_HEADERS,
        ),
        (
            "_Entries_V2",
            ENTRY_V2_HEADERS,
        ),
        (
            "_Entry History",
            ENTRY_HISTORY_HEADERS,
        ),
        (
            "_Author Rules",
            AUTHOR_RULE_HEADERS,
        ),
    ]

    for sheet, headers in schemas:
        sheets.ensure_headers(
            sheet,
            headers,
        )


def load_v2_snapshot(
    sheets: SheetsAdapter,
    *,
    refresh: bool = False,
) -> BackendSnapshot:
    """
    Load all decision-grade v2 backend state using one
    Google Sheets values.batchGet request.
    """

    batch = sheets.batch_get_values(
        V2_SNAPSHOT_SHEETS,
        refresh=refresh,
    )

    return snapshot_from_batch_values(
        batch
    )


def author_rules_from_snapshot(
    snapshot: BackendSnapshot,
):
    from author_resolution import AuthorRule

    rules = []

    for row in snapshot.author_rules:
        rule_id = str(
            row.get("Rule ID", "")
        ).strip()

        canonical_author = str(
            row.get(
                "Canonical Author",
                "",
            )
        ).strip()

        if not rule_id or not canonical_author:
            continue

        rules.append(
            AuthorRule(
                rule_id=rule_id,
                scope=str(
                    row.get(
                        "Scope",
                        "",
                    )
                ).strip().upper(),
                document_key=str(
                    row.get(
                        "Document Key",
                        "",
                    )
                ).strip(),
                version_id=str(
                    row.get(
                        "Version ID",
                        "",
                    )
                ).strip(),
                root_entry_id=str(
                    row.get(
                        "Root Entry ID",
                        "",
                    )
                ).strip(),
                entry_id=str(
                    row.get(
                        "Entry ID",
                        "",
                    )
                ).strip(),
                raw_author=str(
                    row.get(
                        "Raw Author",
                        "",
                    )
                ).strip(),
                canonical_author=(
                    canonical_author
                ),
                status=str(
                    row.get(
                        "Status",
                        "APPROVED",
                    )
                ).strip().upper(),
            )
        )

    return rules
