import pytest

from v2_pm_cell_plan import PM_HEADER_SEQUENCE
from v2_pm_export_coordinator import prepare_new_root_insertions


OLD = "root-old"
NEW = "root-new"


def projected(root_id):
    return {
        "Root Entry ID": root_id,
        "Book Page": "10",
        "PDF Page": "12",
        "Author": "Known Author",
        "Last Modified": "2026-10-15",
        "Comment": "Comment for " + root_id,
        "Reply Entry IDs": "",
        "Annotation Type": "Text",
    }


def backend(root_id):
    return {
        "Entry ID": root_id,
        "Relation Type": "ROOT",
        "Active": "TRUE",
        "Entry Key": "key-" + root_id,
        "Document Key": "TEST",
        "Version ID": "test-v2",
        "Drive File ID": "drive-file",
        "Drive Link": "https://example.com/pdf",
        "PDF SHA256": "a" * 64,
        "PDF Page": "12",
        "Created Date": "2026-10-14",
        "Modified Date": "2026-10-15",
    }


def pm_row(root_id):
    row = [""] * 22
    row[14] = root_id
    row[4] = "Comment for " + root_id
    row[8] = "Human category"
    return row


def test_new_root_is_planned_for_append():
    result = prepare_new_root_insertions(
        [list(PM_HEADER_SEQUENCE), pm_row(OLD)],
        [projected(OLD)],
        [projected(OLD), projected(NEW)],
        [backend(OLD), backend(NEW)],
    )

    assert result["new_root_count"] == 1
    assert len(result["new_rows"]) == 1
    assert result["new_rows"][0][14] == NEW
    assert len(result["existing_pm_values"]) == 2
    assert len(result["existing_current_projection"]) == 1


def test_retry_recognizes_already_appended_root():
    from v2_pm_staging_snapshot import new_root_row

    existing_new = new_root_row(projected(NEW), backend(NEW))

    result = prepare_new_root_insertions(
        [list(PM_HEADER_SEQUENCE), pm_row(OLD), existing_new],
        [projected(OLD)],
        [projected(OLD), projected(NEW)],
        [backend(OLD), backend(NEW)],
    )

    assert result["new_rows"] == []
    assert result["already_present"] == [NEW]
    assert result["new_root_count"] == 1


def test_appended_root_conflict_is_blocked():
    from v2_pm_staging_snapshot import new_root_row

    changed = new_root_row(projected(NEW), backend(NEW))
    changed[4] = "Different comment"

    with pytest.raises(RuntimeError, match="APPENDED_ROOT_CONTENT_CONFLICT"):
        prepare_new_root_insertions(
            [list(PM_HEADER_SEQUENCE), pm_row(OLD), changed],
            [projected(OLD)],
            [projected(OLD), projected(NEW)],
            [backend(OLD), backend(NEW)],
        )


def test_missing_old_root_is_blocked():
    with pytest.raises(RuntimeError, match="PREVIOUS_PM_ROOT_MISSING"):
        prepare_new_root_insertions(
            [list(PM_HEADER_SEQUENCE)],
            [projected(OLD)],
            [projected(OLD), projected(NEW)],
            [backend(OLD), backend(NEW)],
        )


def test_unknown_pm_root_is_blocked():
    with pytest.raises(RuntimeError, match="UNEXPECTED_PM_ROOT_ID"):
        prepare_new_root_insertions(
            [
                list(PM_HEADER_SEQUENCE),
                pm_row(OLD),
                pm_row("unexpected-root"),
            ],
            [projected(OLD)],
            [projected(OLD), projected(NEW)],
            [backend(OLD), backend(NEW)],
        )


def test_source_root_removal_is_blocked():
    with pytest.raises(
        RuntimeError, match="SOURCE_ROOT_REMOVAL_REQUIRES_REVIEW"
    ):
        prepare_new_root_insertions(
            [list(PM_HEADER_SEQUENCE), pm_row(OLD)],
            [projected(OLD)],
            [],
            [backend(OLD)],
        )


def test_coordinator_retry_preserves_new_root_human_category():
    from v2_pm_staging_snapshot import new_root_row

    inserted = new_root_row(projected(NEW), backend(NEW))
    inserted[8] = "PM assigned category"

    result = prepare_new_root_insertions(
        [list(PM_HEADER_SEQUENCE), pm_row(OLD), inserted],
        [projected(OLD)],
        [projected(OLD), projected(NEW)],
        [backend(OLD), backend(NEW)],
    )

    assert result["new_rows"] == []
    assert result["already_present"] == [NEW]
