import copy

import pytest

from v2_pm_cell_plan import PM_HEADER_SEQUENCE
from v2_pm_root_writer import (
    GuardedRootAppender,
    PMRootInsertConflict,
)


class Request:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result()


class FakeSheets:
    def __init__(self):
        first = [""] * 22
        first[4] = "Existing human-reviewed comment"
        first[8] = "Manual category"
        first[14] = "root-existing"

        self.rows = [
            list(PM_HEADER_SEQUENCE),
            first,
        ]
        self.append_count = 0

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, **kwargs):
        if "range" in kwargs:
            return Request(lambda: {
                "values": copy.deepcopy(self.rows)
            })

        return Request(lambda: {
            "sheets": [{
                "properties": {
                    "sheetId": 123,
                    "title": "PM",
                },
            }],
        })

    def batchUpdate(self, **kwargs):
        def perform():
            request = kwargs["body"]["requests"][0]
            operation = request["appendCells"]

            assert operation["sheetId"] == 123
            assert operation["fields"] == "userEnteredValue"

            cells = operation["rows"][0]["values"]
            row = [
                cell.get("userEnteredValue", {}).get(
                    "stringValue", ""
                )
                for cell in cells
            ]

            self.rows.append(row)
            self.append_count += 1
            return {}

        return Request(perform)


def desired():
    row = [""] * 22
    row[4] = "New PDF comment"
    row[14] = "root-new"
    row[15] = "new-entry-key"
    return row


def writer(service):
    return GuardedRootAppender(
        service,
        "staging",
        "PM",
        authorized_spreadsheet_id="staging",
        authorized_tab="PM",
    )


def test_root_insertion_preserves_existing_rows():
    service = FakeSheets()
    before = copy.deepcopy(service.rows)

    result = writer(service).apply(
        desired(), allow_writes=True
    )

    assert result["verified"] is True
    assert result["action"] == "INSERTED"
    assert service.rows[:2] == before
    assert service.rows[2] == desired()
    assert service.append_count == 1


def test_root_retry_is_idempotent():
    service = FakeSheets()
    instance = writer(service)

    instance.apply(desired(), allow_writes=True)
    result = instance.apply(
        desired(), allow_writes=True
    )

    assert result["action"] == "ALREADY_PRESENT"
    assert service.append_count == 1


def test_dry_run_never_writes():
    service = FakeSheets()
    result = writer(service).apply(desired())

    assert result["action"] == "INSERT_CANDIDATE"
    assert service.append_count == 0


def test_conflicting_existing_root_is_blocked():
    service = FakeSheets()
    instance = writer(service)
    instance.apply(desired(), allow_writes=True)

    changed = desired()
    changed[4] = "Unexpected content"

    with pytest.raises(
        PMRootInsertConflict,
        match="EXISTING_ROOT_CONTENT_CONFLICT",
    ):
        instance.apply(changed, allow_writes=True)

    assert service.append_count == 1


def test_duplicate_identity_is_blocked():
    service = FakeSheets()
    service.rows.append(copy.deepcopy(service.rows[1]))

    with pytest.raises(
        PMRootInsertConflict,
        match="DUPLICATE_PM_ROOT_ID",
    ):
        writer(service).apply(desired(), allow_writes=True)


def test_production_destination_is_not_authorized():
    service = FakeSheets()

    with pytest.raises(PermissionError):
        GuardedRootAppender(
            service,
            "production",
            "PM",
            authorized_spreadsheet_id="staging",
            authorized_tab="PM",
        )


def test_root_retry_preserves_manually_assigned_category():
    service = FakeSheets()
    instance = writer(service)

    instance.apply(desired(), allow_writes=True)

    # A PM assigns a category after PrOps appended the ROOT.
    service.rows[2][8] = "Manually reviewed category"

    result = instance.apply(
        desired(), allow_writes=True
    )

    assert result["action"] == "ALREADY_PRESENT"
    assert service.rows[2][8] == "Manually reviewed category"
    assert service.append_count == 1


def test_root_retry_rejects_modified_source_owned_comment():
    service = FakeSheets()
    instance = writer(service)

    instance.apply(desired(), allow_writes=True)
    service.rows[2][4] = "Unapproved comment modification"

    with pytest.raises(
        PMRootInsertConflict,
        match="EXISTING_ROOT_CONTENT_CONFLICT",
    ):
        instance.apply(desired(), allow_writes=True)

    assert service.append_count == 1
