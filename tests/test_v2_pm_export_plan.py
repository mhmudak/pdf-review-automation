from copy import deepcopy

import pytest

from v2_pm_export_plan import build_pm_export_plan


def row(entry_id, **fields):
    return {"Root Entry ID": entry_id, **fields}


def test_identical_rows_produce_zero_changes():
    result = build_pm_export_plan(
        [row("r1", Comment="Hello")],
        [row("r1", Comment="Hello")],
    )
    assert result["matched_count"] == 1
    assert result["differences"] == []
    assert result["write_operations"] == []


def test_new_root_is_identified_without_writing():
    result = build_pm_export_plan(
        [row("r1")],
        [row("r1"), row("r2", Comment="New")],
    )
    assert result["new_count"] == 1
    assert result["new_rows"][0]["Root Entry ID"] == "r2"
    assert result["write_operations"] == []


def test_historical_pm_row_is_preserved():
    result = build_pm_export_plan(
        [row("r1"), row("historic")],
        [row("r1")],
    )
    assert result["preserved_count"] == 1
    assert result["preserved_rows"][0]["Root Entry ID"] == "historic"
    assert result["deletion_operations"] == []


def test_manual_category_never_becomes_authorized_update():
    result = build_pm_export_plan(
        [row("r1", Category="Approved")],
        [row("r1", Category="")],
    )
    assert result["differences"][0]["classification"] == (
        "PROTECTED_DIFFERENCE"
    )
    assert result["existing_row_updates_authorized"] is False


def test_unresolved_author_difference_is_held():
    result = build_pm_export_plan(
        [row("r1", Author="Existing PM name")],
        [row("r1", Author="Different projected name")],
    )
    assert result["differences"][0]["field"] == "Author"
    assert result["write_operations"] == []


def test_reply_format_difference_is_held():
    result = build_pm_export_plan(
        [row("r1", **{"Reply 1": "Original display"})],
        [row("r1", **{"Reply 1": "New display"})],
    )
    assert result["differences"][0]["classification"] == (
        "PROTECTED_DIFFERENCE"
    )


def test_changed_comment_is_not_automatically_overwritten():
    result = build_pm_export_plan(
        [row("r1", Comment="Old")],
        [row("r1", Comment="New")],
    )
    assert result["differences"][0]["classification"] == (
        "UNVERIFIED_SOURCE_DIFFERENCE"
    )
    assert result["write_operations"] == []


@pytest.mark.parametrize("dataset", ["existing", "projected"])
def test_duplicate_ids_are_rejected(dataset):
    old = [row("r1")]
    new = [row("r1")]
    if dataset == "existing":
        old.append(row("r1"))
    else:
        new.append(row("r1"))

    with pytest.raises(ValueError):
        build_pm_export_plan(old, new)


def test_input_rows_are_not_mutated():
    old = [row("r1", Category="Manual")]
    new = [row("r1", Category="")]
    before_old, before_new = deepcopy(old), deepcopy(new)

    build_pm_export_plan(old, new)

    assert old == before_old
    assert new == before_new
