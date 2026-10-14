import pytest

from v2_pm_cell_plan import PM_HEADER_SEQUENCE
from v2_pm_staging_snapshot import build_sorted_staging_snapshot


def existing(root, category="", comment=""):
    row = [""] * 22
    row[14] = root
    row[8] = category
    row[4] = comment
    return row


def projected(root, comment=""):
    return {"Root Entry ID": root, "Comment": comment}


def backend(root):
    return {
        "Entry ID": root,
        "Entry Key": "key-" + root,
        "Relation Type": "ROOT",
        "Active": "TRUE",
        "Document Key": "doc",
        "Version ID": "v2",
        "Drive File ID": "drive",
        "PDF SHA256": "a" * 64,
        "Content": "New",
    }


def build(rows, projection, backend_rows=()):
    return build_sorted_staging_snapshot(
        [list(PM_HEADER_SEQUENCE), *rows],
        projection,
        list(backend_rows),
    )


def test_identical_order_preserves_every_cell():
    a = existing("a", "Manual", "Original")
    result = build([a], [projected("a", "Changed")])
    assert result["rows"] == [a]
    assert result["manual_categories_preserved"] == 1


def test_reorders_whole_rows_without_detaching_categories():
    a = existing("a", "Category A")
    b = existing("b", "Category B")
    result = build([a, b], [projected("b"), projected("a")])
    assert result["rows"] == [b, a]


def test_new_root_inserted_in_correct_order():
    a = existing("a")
    c = existing("c")
    result = build(
        [a, c],
        [projected("a"), projected("b", "New"), projected("c")],
        [backend("b")],
    )
    assert [r[14] for r in result["rows"]] == ["a", "b", "c"]
    assert result["rows"][1][4] == "New"
    assert result["inserted_count"] == 1


def test_historical_root_is_retained():
    result = build(
        [existing("old"), existing("a")],
        [projected("a")],
    )
    assert [r[14] for r in result["rows"]] == ["a", "old"]
    assert result["historical_preserved_count"] == 1


def test_missing_backend_new_root_is_rejected():
    with pytest.raises(ValueError):
        build([], [projected("new")])


def test_duplicate_projection_ids_are_rejected():
    with pytest.raises(ValueError):
        build([], [projected("a"), projected("a")])


def test_no_writes_or_deletions():
    result = build([existing("a")], [projected("a")])
    assert result["google_write_operations"] == []
    assert result["deletion_operations"] == []


def test_new_root_has_complete_identity_metadata():
    result = build([], [projected("b")], [backend("b")])
    row = result["rows"][0]
    assert row[14] == "b"
    assert row[15] == "key-b"
    assert row[16] == "v2"
    assert row[18] == "a" * 64
