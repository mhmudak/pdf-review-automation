from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend_cache import BackendSnapshot


@dataclass(frozen=True)
class PlannedEntryChange:
    change_type: str
    document_key: str
    entry_id: str
    current: dict[str, Any] | None
    previous: dict[str, Any] | None


@dataclass(frozen=True)
class V2ChangePlan:
    document_key: str
    changes: tuple[PlannedEntryChange, ...]

    @property
    def new(self) -> tuple[PlannedEntryChange, ...]:
        return tuple(
            item
            for item in self.changes
            if item.change_type == "NEW"
        )

    @property
    def updated(self) -> tuple[PlannedEntryChange, ...]:
        return tuple(
            item
            for item in self.changes
            if item.change_type == "UPDATED"
        )

    @property
    def unchanged(self) -> tuple[PlannedEntryChange, ...]:
        return tuple(
            item
            for item in self.changes
            if item.change_type == "UNCHANGED"
        )

    @property
    def author_updated(self) -> tuple[PlannedEntryChange, ...]:
        return tuple(
            item
            for item in self.changes
            if item.change_type == "AUTHOR_UPDATED"
        )

    @property
    def removed(self) -> tuple[PlannedEntryChange, ...]:
        return tuple(
            item
            for item in self.changes
            if item.change_type == "REMOVED"
        )

    def counts(self) -> dict[str, int]:
        return {
            "NEW": len(self.new),
            "UPDATED": len(self.updated),
            "AUTHOR_UPDATED": len(self.author_updated),
            "UNCHANGED": len(self.unchanged),
            "REMOVED": len(self.removed),
        }


def _old_signature(
    row: dict[str, Any],
) -> str:
    return str(
        row.get(
            "Entry Signature",
            "",
        )
    ).strip()


def _old_active(
    row: dict[str, Any],
) -> bool:
    value = row.get(
        "Active",
        True,
    )

    if isinstance(value, bool):
        return value

    return (
        str(value)
        .strip()
        .lower()
        not in {
            "",
            "false",
            "0",
            "no",
            "inactive",
        }
    )


def _new_entry_id(
    row: dict[str, Any],
) -> str:
    return str(
        row.get(
            "entry_id",
            "",
        )
    ).strip()


def _new_signature(
    row: dict[str, Any],
) -> str:
    return str(
        row.get(
            "entry_signature",
            "",
        )
    ).strip()


def _author_resolution_changed(
    previous: dict[str, Any],
    current: dict[str, Any],
) -> bool:
    pairs = (
        (
            "Canonical Author",
            "canonical_author",
        ),
        (
            "Author Status",
            "author_status",
        ),
        (
            "Author Resolution Method",
            "author_resolution_method",
        ),
        (
            "Author Rule ID",
            "author_rule_id",
        ),
    )

    for old_key, new_key in pairs:
        old_value = str(
            previous.get(
                old_key,
                "",
            )
        ).strip()

        new_value = str(
            current.get(
                new_key,
                "",
            )
        ).strip()

        if old_value != new_value:
            return True

    return False


def plan_v2_changes(
    snapshot: BackendSnapshot,
    document_key: str,
    prepared_entries: list[dict[str, Any]],
) -> V2ChangePlan:
    """
    Compare the canonical backend state for one logical
    document with newly prepared PDF entries.

    This function is deliberately pure:
    no API calls and no writes.
    """

    document_key = str(
        document_key
    ).strip()

    if not document_key:
        raise ValueError(
            "document_key is required"
        )

    current_by_id: dict[
        str,
        dict[str, Any],
    ] = {}

    for row in prepared_entries:
        row_document_key = str(
            row.get(
                "document_key",
                "",
            )
        ).strip()

        if (
            row_document_key
            and row_document_key != document_key
        ):
            raise ValueError(
                "Prepared entry belongs to a "
                "different document."
            )

        entry_id = _new_entry_id(
            row
        )

        if not entry_id:
            raise ValueError(
                "Prepared entry is missing entry_id."
            )

        signature = _new_signature(
            row
        )

        if not signature:
            raise ValueError(
                "Prepared entry is missing "
                "entry_signature."
            )

        if entry_id in current_by_id:
            raise ValueError(
                "Duplicate prepared Entry ID: "
                f"{entry_id!r}"
            )

        current_by_id[
            entry_id
        ] = row

    previous_rows = (
        snapshot.entries_for_document(
            document_key
        )
    )

    previous_by_id: dict[
        str,
        dict[str, Any],
    ] = {}

    for row in previous_rows:
        entry_id = str(
            row.get(
                "Entry ID",
                "",
            )
        ).strip()

        if not entry_id:
            continue

        if entry_id in previous_by_id:
            raise ValueError(
                "Duplicate canonical backend "
                f"Entry ID for {document_key!r}: "
                f"{entry_id!r}"
            )

        previous_by_id[
            entry_id
        ] = row

    changes: list[
        PlannedEntryChange
    ] = []

    # Current PDF entries.
    for entry_id, current in current_by_id.items():
        previous = previous_by_id.get(
            entry_id
        )

        if previous is None:
            change_type = "NEW"

        elif not _old_active(previous):
            # Entry existed historically but was inactive.
            # Reappearance changes canonical state.
            change_type = "UPDATED"

        elif (
            _old_signature(previous)
            != _new_signature(current)
        ):
            change_type = "UPDATED"

        elif _author_resolution_changed(
            previous,
            current,
        ):
            change_type = "AUTHOR_UPDATED"

        else:
            change_type = "UNCHANGED"

        changes.append(
            PlannedEntryChange(
                change_type=change_type,
                document_key=document_key,
                entry_id=entry_id,
                current=current,
                previous=previous,
            )
        )

    # Entries previously active but absent from newest PDF.
    for entry_id, previous in previous_by_id.items():
        if entry_id in current_by_id:
            continue

        if not _old_active(previous):
            # Already historical/inactive.
            # Do not repeatedly emit REMOVED.
            continue

        changes.append(
            PlannedEntryChange(
                change_type="REMOVED",
                document_key=document_key,
                entry_id=entry_id,
                current=None,
                previous=previous,
            )
        )

    changes.sort(
        key=lambda item: (
            item.entry_id,
            item.change_type,
        )
    )

    return V2ChangePlan(
        document_key=document_key,
        changes=tuple(changes),
    )
