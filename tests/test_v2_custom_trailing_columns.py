import pytest
from unittest.mock import MagicMock
from v2_pm_cell_plan import PM_HEADER_SEQUENCE
from v2_pm_export_coordinator import read_pm_grid, pm_column_letter


def adapter(values, width):
    api = MagicMock()
    api.service.spreadsheets.return_value.get.return_value.execute.return_value = {
        "sheets": [{"properties": {"title": "Trial PDF - All Data", "gridProperties": {"columnCount": width}}}]
    }
    api.service.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {"values": values}
    api.spreadsheet_id = "staging"
    return api


def test_blank_w_is_accepted():
    a = adapter([list(PM_HEADER_SEQUENCE)], 23)
    assert read_pm_grid(a, "Trial PDF - All Data") == [list(PM_HEADER_SEQUENCE)]
    assert "A1:W" in str(a.service.spreadsheets.return_value.values.return_value.get.call_args)


def test_populated_custom_w_is_preserved_and_not_forwarded_to_writer():
    headers = list(PM_HEADER_SEQUENCE) + ["PM Notes"]
    row = [""] * 23
    row[14] = "root-1"
    row[22] = "Human note DO NOT OVERWRITE"
    result = read_pm_grid(adapter([headers, row], 23), "Trial PDF - All Data")
    assert len(result[0]) == 22
    assert len(result[1]) == 22
    assert result[1][14] == "root-1"


def test_named_custom_column_between_system_columns_is_preserved():
    headers = list(PM_HEADER_SEQUENCE)
    headers.insert(9, "PM Notes")
    row = [""] * 23
    row[9] = "Human data"
    row[15] = "root-1"
    result = read_pm_grid(adapter([headers, row], 23), "Trial PDF - All Data")
    assert result[0] == list(PM_HEADER_SEQUENCE)
    assert len(result[1]) == 22
    assert result[1][14] == "root-1"


def test_unnamed_populated_custom_column_rejected():
    row = [""] * 23
    row[22] = "Unlabeled human content"
    with pytest.raises(RuntimeError, match="PM_UNNAMED_COLUMN_WITH_DATA"):
        read_pm_grid(adapter([list(PM_HEADER_SEQUENCE), row], 23), "Trial PDF - All Data")


def test_duplicate_custom_header_rejected():
    headers = list(PM_HEADER_SEQUENCE) + ["Notes", "Notes"]
    with pytest.raises(RuntimeError, match="PM_DUPLICATE_HEADER"):
        read_pm_grid(adapter([headers], 24), "Trial PDF - All Data")


def test_shadowed_system_header_rejected():
    headers = list(PM_HEADER_SEQUENCE) + ["Category"]
    with pytest.raises(RuntimeError, match="PM_DUPLICATE_HEADER"):
        read_pm_grid(adapter([headers], 23), "Trial PDF - All Data")


def test_column_letter_over_26():
    assert [pm_column_letter(i) for i in (22, 23, 26, 27, 28)] == ["V", "W", "Z", "AA", "AB"]
