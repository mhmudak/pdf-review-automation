import pytest

from v2_pm_checkpoint import (
    new_export_checkpoint,
    advance_checkpoint,
)
from v2_pm_checkpoint_adapter import (
    get_checkpoint,
    persist_checkpoint,
    read_checkpoint_table,
)
from v2_pm_checkpoint_store import PM_EXPORT_HEADERS


class FakeSheets:
    def __init__(self, rows=None, headers=None):
        self.rows = [
            list(headers if headers is not None
                 else PM_EXPORT_HEADERS),
            *(list(row) for row in (rows or [])),
        ]
        self.writes = 0

    def get_all_values(self, tab, refresh=False):
        return [list(row) for row in self.rows]

    def append_rows(self, tab, rows):
        self.writes += 1
        self.rows.extend(list(row) for row in rows)

    def batch_update_rows(self, tab, updates):
        self.writes += 1
        for number, row in updates:
            self.rows[number - 1] = list(row)


def checkpoint():
    return new_export_checkpoint(
        document_key="IGCSE_ARABIC_2P",
        version_id="v2",
        pdf_sha256="a" * 64,
        output_spreadsheet_id="pm-staging",
        output_tab="Staging",
        previous_exported_version_id="v1",
    )


def test_empty_table_with_headers_is_valid():
    assert read_checkpoint_table(FakeSheets()) == []


def test_schema_mismatch_rejected():
    with pytest.raises(ValueError):
        read_checkpoint_table(FakeSheets(headers=["Wrong"]))


def test_writes_disabled_by_default():
    fake = FakeSheets()
    result = persist_checkpoint(fake, checkpoint())
    assert result["action"] == "INSERT_CANDIDATE"
    assert result["written"] is False
    assert fake.writes == 0


def test_explicit_insert_and_readback():
    fake = FakeSheets()
    c = checkpoint()
    result = persist_checkpoint(
        fake, c, allow_writes=True
    )
    assert result["written"] is True
    assert result["verified"] is True
    assert get_checkpoint(fake, c["export_id"])["state"] == (
        "EXPORT_PENDING"
    )


def test_repeated_insert_is_noop():
    fake = FakeSheets()
    c = checkpoint()
    persist_checkpoint(fake, c, allow_writes=True)
    result = persist_checkpoint(fake, c, allow_writes=True)
    assert result["action"] == "NOOP"
    assert result["verified"] is True
    assert fake.writes == 1


def test_valid_state_update():
    fake = FakeSheets()
    old = checkpoint()
    persist_checkpoint(fake, old, allow_writes=True)

    started = advance_checkpoint(old, "START_EXPORT")
    result = persist_checkpoint(
        fake, started, allow_writes=True
    )
    assert result["action"] == "UPDATE_CANDIDATE"
    assert get_checkpoint(fake, old["export_id"])["attempts"] == 1


def test_invalid_state_jump_rejected():
    fake = FakeSheets()
    old = checkpoint()
    persist_checkpoint(fake, old, allow_writes=True)

    invalid = dict(old)
    invalid["state"] = "COMPLETED"

    with pytest.raises(ValueError):
        persist_checkpoint(
            fake, invalid, allow_writes=True
        )


def test_duplicate_export_ids_rejected():
    from v2_pm_checkpoint_store import serialize_checkpoint

    c = checkpoint()
    row = serialize_checkpoint(c)
    fake = FakeSheets(rows=[row, row])

    with pytest.raises(ValueError):
        read_checkpoint_table(fake)


def test_read_only_lookup_of_missing_record():
    fake = FakeSheets()
    assert get_checkpoint(fake, "missing") is None
    assert fake.writes == 0


def test_failed_readback_blocks_confirmation():
    class CorruptingSheets(FakeSheets):
        def append_rows(self, tab, rows):
            super().append_rows(tab, rows)
            self.rows[-1][7] = "COMPLETED"

    fake = CorruptingSheets()

    with pytest.raises(RuntimeError):
        persist_checkpoint(
            fake, checkpoint(), allow_writes=True
        )
