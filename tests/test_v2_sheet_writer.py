import pytest

from sheets_adapter import (
    ENTRY_HISTORY_HEADERS,
    ENTRY_V2_HEADERS,
)
from v2_mutations import V2MutationSet
from v2_sheet_writer import (
    apply_v2_mutations,
    dict_to_row,
)


class FakeSheets:
    def __init__(self, rows=None):
        self.rows = rows or {}
        self.key_lookup_calls = 0
        self.batch_updates = []
        self.appends = []

    def key_to_row(
        self,
        sheet,
        key_col=0,
    ):
        self.key_lookup_calls += 1
        assert sheet == "_Entries_V2"
        assert key_col == 0
        return dict(self.rows)

    def batch_update_rows(
        self,
        sheet,
        updates,
    ):
        self.batch_updates.append(
            (sheet, updates)
        )

    def append_rows(
        self,
        sheet,
        rows,
    ):
        self.appends.append(
            (sheet, rows)
        )


def mutation_set(
    *,
    inserts=(),
    updates=(),
    deactivations=(),
    history=(),
):
    return V2MutationSet(
        insert_entries=tuple(inserts),
        update_entries=tuple(updates),
        deactivate_entries=tuple(
            deactivations
        ),
        history_rows=tuple(history),
    )


def canonical(
    key,
    *,
    active=True,
):
    return {
        "Entry Key": key,
        "Document Key": "BOOK",
        "Version ID": "BOOK@v2",
        "Entry ID": key.split("::")[-1],
        "Entry Signature": "sig",
        "Active": active,
        "Source State": (
            "CURRENT"
            if active
            else "HISTORICAL"
        ),
    }


def history(key):
    return {
        "History Key": f"H::{key}",
        "Document Key": "BOOK",
        "Version ID": "BOOK@v2",
        "Entry ID": key.split("::")[-1],
        "Entry Signature": "sig",
        "Change Type": "UPDATED",
        "Recorded At": "2026-10-12T20:00:00+00:00",
    }


def test_dict_to_row_uses_schema_order():
    record = {
        "Entry ID": "A",
        "Entry Key": "BOOK::A",
        "Active": True,
    }

    row = dict_to_row(
        record,
        ENTRY_V2_HEADERS,
    )

    assert len(row) == len(
        ENTRY_V2_HEADERS
    )

    assert row[
        ENTRY_V2_HEADERS.index(
            "Entry Key"
        )
    ] == "BOOK::A"

    assert row[
        ENTRY_V2_HEADERS.index(
            "Entry ID"
        )
    ] == "A"

    assert row[
        ENTRY_V2_HEADERS.index(
            "Active"
        )
    ] is True


def test_empty_mutations_do_zero_sheet_work():
    sheets = FakeSheets()

    result = apply_v2_mutations(
        sheets,
        mutation_set(),
    )

    assert result == {
        "inserted": 0,
        "updated": 0,
        "deactivated": 0,
        "history_appended": 0,
    }

    assert sheets.key_lookup_calls == 0
    assert sheets.batch_updates == []
    assert sheets.appends == []


def test_insert_and_history_use_two_appends():
    sheets = FakeSheets()

    result = apply_v2_mutations(
        sheets,
        mutation_set(
            inserts=[
                canonical(
                    "BOOK::A"
                )
            ],
            history=[
                history(
                    "BOOK::A"
                )
            ],
        ),
    )

    assert result["inserted"] == 1
    assert result["history_appended"] == 1

    assert sheets.key_lookup_calls == 0
    assert len(sheets.appends) == 2

    assert (
        sheets.appends[0][0]
        == "_Entries_V2"
    )

    assert (
        sheets.appends[1][0]
        == "_Entry History"
    )

    assert len(
        sheets.appends[0][1][0]
    ) == len(ENTRY_V2_HEADERS)

    assert len(
        sheets.appends[1][1][0]
    ) == len(ENTRY_HISTORY_HEADERS)


def test_updates_and_deactivations_share_one_batch():
    sheets = FakeSheets(
        rows={
            "BOOK::A": 2,
            "BOOK::B": 3,
        }
    )

    result = apply_v2_mutations(
        sheets,
        mutation_set(
            updates=[
                canonical(
                    "BOOK::A"
                )
            ],
            deactivations=[
                canonical(
                    "BOOK::B",
                    active=False,
                )
            ],
        ),
    )

    assert result["updated"] == 1
    assert result["deactivated"] == 1

    assert sheets.key_lookup_calls == 1
    assert len(
        sheets.batch_updates
    ) == 1

    sheet, updates = (
        sheets.batch_updates[0]
    )

    assert sheet == "_Entries_V2"

    assert [
        row_number
        for row_number, _ in updates
    ] == [2, 3]


def test_missing_existing_row_fails_before_writes():
    sheets = FakeSheets(
        rows={}
    )

    with pytest.raises(
        ValueError,
        match="not found",
    ):
        apply_v2_mutations(
            sheets,
            mutation_set(
                updates=[
                    canonical(
                        "BOOK::A"
                    )
                ],
                inserts=[
                    canonical(
                        "BOOK::B"
                    )
                ],
                history=[
                    history(
                        "BOOK::A"
                    )
                ],
            ),
        )

    assert sheets.batch_updates == []
    assert sheets.appends == []


def test_duplicate_existing_mutation_fails_closed():
    sheets = FakeSheets(
        rows={
            "BOOK::A": 2,
        }
    )

    with pytest.raises(
        ValueError,
        match="Duplicate mutation",
    ):
        apply_v2_mutations(
            sheets,
            mutation_set(
                updates=[
                    canonical(
                        "BOOK::A"
                    )
                ],
                deactivations=[
                    canonical(
                        "BOOK::A",
                        active=False,
                    )
                ],
            ),
        )

    assert sheets.batch_updates == []
    assert sheets.appends == []
