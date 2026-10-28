import copy

import pytest

from v2_pm_reconciliation import reconcile_pm_rows


def row(entry_id, **values):
    result = {"Root Entry ID": entry_id}
    result.update(values)
    return result


def test_identical_datasets_require_no_writes():
    existing = [row("A"), row("B")]
    projected = [row("A"), row("B")]

    result = reconcile_pm_rows(existing, projected)

    assert result["matched_count"] == 2
    assert result["new_count"] == 0
    assert result["preserved_count"] == 0
    assert result["write_operations"] == []


def test_new_records_identified_once():
    result = reconcile_pm_rows(
        [row("A")],
        [row("A"), row("B")],
    )

    assert result["new_count"] == 1
    assert [x["Root Entry ID"] for x in result["new"]] == ["B"]


def test_old_records_never_deleted():
    result = reconcile_pm_rows(
        [row("A"), row("OLD", Comment="Historical review")],
        [row("A")],
    )

    assert result["preserved_count"] == 1
    assert result["preserved"][0]["Comment"] == (
        "Historical review"
    )
    assert result["deletion_operations"] == []


def test_existing_manual_category_is_preserved():
    existing = [
        row("A", Category="Language", Comment="Original")
    ]
    projected = [
        row("A", Category="", Comment="Updated")
    ]

    before = copy.deepcopy(existing)

    result = reconcile_pm_rows(existing, projected)

    assert existing == before
    assert result["matched"][0]["existing"]["Category"] == (
        "Language"
    )
    assert result["write_operations"] == []


@pytest.mark.parametrize(
    "existing,projected",
    [
        ([row("A"), row("A")], [row("A")]),
        ([row("A")], [row("B"), row("B")]),
        ([row("")], [row("A")]),
        ([row("A")], [row("")]),
    ],
)
def test_ambiguous_identities_stop_export(existing, projected):
    with pytest.raises(ValueError):
        reconcile_pm_rows(existing, projected)


def test_input_order_is_not_changed():
    existing = [row("C"), row("A"), row("B")]
    projected = [row("A"), row("D")]

    result = reconcile_pm_rows(existing, projected)

    assert [
        x["Root Entry ID"] for x in result["preserved"]
    ] == ["C", "B"]

    assert [
        x["Root Entry ID"] for x in result["new"]
    ] == ["D"]
