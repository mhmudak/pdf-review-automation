from __future__ import annotations

from typing import Any

from sheets_adapter import (
    ENTRY_HISTORY_HEADERS,
    ENTRY_V2_HEADERS,
    SheetsAdapter,
)
from v2_mutations import V2MutationSet


def dict_to_row(
    record: dict[str, Any],
    headers: list[str],
) -> list[Any]:
    """
    Serialize a dictionary in the exact Google Sheet
    schema order.
    """
    return [
        record.get(header, "")
        for header in headers
    ]


def apply_v2_mutations(
    sheets: SheetsAdapter,
    mutations: V2MutationSet,
) -> dict[str, int]:
    """
    Apply minimal v2 mutations.

    Important:
    - UNCHANGED entries never reach this function.
    - Existing-row positions are validated before any
      write occurs.
    - Updates + deactivations use one batchUpdate call.
    - New entries use one append call.
    - History uses one append call.
    """

    inserts = list(
        mutations.insert_entries
    )

    existing_changes = [
        *mutations.update_entries,
        *mutations.deactivate_entries,
    ]

    history = list(
        mutations.history_rows
    )

    # Completely idle mutation set:
    # zero Google writes and zero row lookups.
    if (
        not inserts
        and not existing_changes
        and not history
    ):
        return {
            "inserted": 0,
            "updated": 0,
            "deactivated": 0,
            "history_appended": 0,
        }

    # -------------------------------------------------
    # PREVALIDATE ALL EXISTING ROW LOCATIONS
    # BEFORE WRITING ANYTHING
    # -------------------------------------------------

    updates: list[
        tuple[int, list[Any]]
    ] = []

    if existing_changes:
        row_by_key = sheets.key_to_row(
            "_Entries_V2",
            key_col=0,
        )

        seen_keys: set[str] = set()

        for record in existing_changes:
            entry_key = str(
                record.get(
                    "Entry Key",
                    "",
                )
            ).strip()

            if not entry_key:
                raise ValueError(
                    "Existing v2 mutation is "
                    "missing Entry Key."
                )

            if entry_key in seen_keys:
                raise ValueError(
                    "Duplicate mutation for "
                    f"Entry Key {entry_key!r}."
                )

            seen_keys.add(entry_key)

            row_number = row_by_key.get(
                entry_key
            )

            if row_number is None:
                raise ValueError(
                    "Canonical _Entries_V2 row "
                    "not found for "
                    f"{entry_key!r}."
                )

            updates.append(
                (
                    row_number,
                    dict_to_row(
                        record,
                        ENTRY_V2_HEADERS,
                    ),
                )
            )

    # -------------------------------------------------
    # VALIDATE NEW ENTRY KEYS
    # -------------------------------------------------

    insert_keys: set[str] = set()

    for record in inserts:
        entry_key = str(
            record.get(
                "Entry Key",
                "",
            )
        ).strip()

        if not entry_key:
            raise ValueError(
                "New v2 entry is missing "
                "Entry Key."
            )

        if entry_key in insert_keys:
            raise ValueError(
                "Duplicate new Entry Key "
                f"{entry_key!r}."
            )

        insert_keys.add(entry_key)

    # -------------------------------------------------
    # WRITES
    # -------------------------------------------------

    # Existing canonical rows:
    # one values.batchUpdate request.
    if updates:
        sheets.batch_update_rows(
            "_Entries_V2",
            updates,
        )

    # New canonical rows:
    # one append request.
    if inserts:
        sheets.append_rows(
            "_Entries_V2",
            [
                dict_to_row(
                    record,
                    ENTRY_V2_HEADERS,
                )
                for record in inserts
            ],
        )

    # Audit history:
    # one append request.
    if history:
        sheets.append_rows(
            "_Entry History",
            [
                dict_to_row(
                    record,
                    ENTRY_HISTORY_HEADERS,
                )
                for record in history
            ],
        )

    return {
        "inserted": len(
            mutations.insert_entries
        ),
        "updated": len(
            mutations.update_entries
        ),
        "deactivated": len(
            mutations.deactivate_entries
        ),
        "history_appended": len(
            mutations.history_rows
        ),
    }
