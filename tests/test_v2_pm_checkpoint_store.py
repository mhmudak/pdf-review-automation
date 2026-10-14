import pytest

from v2_pm_checkpoint import (
    new_export_checkpoint,
    advance_checkpoint,
)
from v2_pm_checkpoint_store import (
    PM_EXPORT_HEADERS,
    serialize_checkpoint,
    deserialize_checkpoint,
    plan_checkpoint_storage,
)


def make_checkpoint(**overrides):
    values = {
        "document_key": "IGCSE_ARABIC_2P",
        "version_id": "v2",
        "pdf_sha256": "a" * 64,
        "output_spreadsheet_id": "pm-sheet",
        "output_tab": "Trial PDF - All Data",
        "previous_exported_version_id": "v1",
    }
    values.update(overrides)
    return new_export_checkpoint(**values)


def test_schema_unique_and_stable():
    assert len(PM_EXPORT_HEADERS) == 12
    assert len(set(PM_EXPORT_HEADERS)) == 12


def test_round_trip():
    original = make_checkpoint()
    restored = deserialize_checkpoint(
        serialize_checkpoint(original)
    )
    assert original == restored


def test_empty_table_plans_insert():
    plan = plan_checkpoint_storage([], make_checkpoint())
    assert plan["action"] == "INSERT_CANDIDATE"
    assert plan["google_write_operations"] == []


def test_existing_identical_record_is_noop():
    checkpoint = make_checkpoint()
    plan = plan_checkpoint_storage(
        [serialize_checkpoint(checkpoint)],
        checkpoint,
    )
    assert plan["action"] == "NOOP"
    assert plan["row_number"] == 2


def test_existing_checkpoint_plans_update():
    old = make_checkpoint()
    new = advance_checkpoint(old, "START_EXPORT")
    plan = plan_checkpoint_storage(
        [serialize_checkpoint(old)], new
    )
    assert plan["action"] == "UPDATE_CANDIDATE"
    assert plan["row_number"] == 2


def test_different_version_plans_new_record():
    old = make_checkpoint()
    new = make_checkpoint(version_id="v3")
    plan = plan_checkpoint_storage(
        [serialize_checkpoint(old)], new
    )
    assert plan["action"] == "INSERT_CANDIDATE"


def test_duplicate_stored_ids_rejected():
    checkpoint = make_checkpoint()
    row = serialize_checkpoint(checkpoint)
    with pytest.raises(ValueError):
        plan_checkpoint_storage([row, row], checkpoint)


def test_identity_conflict_rejected():
    checkpoint = make_checkpoint()
    changed = dict(checkpoint)
    changed["output_tab"] = "Other"
    with pytest.raises(ValueError):
        plan_checkpoint_storage(
            [serialize_checkpoint(checkpoint)], changed
        )


def test_baseline_change_rejected():
    checkpoint = make_checkpoint()
    changed = dict(checkpoint)
    changed["previous_exported_version_id"] = "wrong"
    with pytest.raises(ValueError):
        plan_checkpoint_storage(
            [serialize_checkpoint(checkpoint)], changed
        )


def test_attempt_counter_cannot_go_backwards():
    original = make_checkpoint()
    started = advance_checkpoint(original, "START_EXPORT")
    with pytest.raises(ValueError):
        plan_checkpoint_storage(
            [serialize_checkpoint(started)], original
        )


def test_completed_checkpoint_cannot_reopen():
    checkpoint = make_checkpoint()
    started = advance_checkpoint(checkpoint, "START_EXPORT")
    verified = advance_checkpoint(
        started,
        "EXPORT_VERIFIED",
        verification_digest="b" * 64,
    )
    completed = advance_checkpoint(
        verified, "COMPLETE_WITHOUT_NOTIFICATION"
    )
    with pytest.raises(ValueError):
        plan_checkpoint_storage(
            [serialize_checkpoint(completed)], started
        )


def test_verified_digest_immutable():
    checkpoint = make_checkpoint()
    started = advance_checkpoint(checkpoint, "START_EXPORT")
    verified = advance_checkpoint(
        started,
        "EXPORT_VERIFIED",
        verification_digest="b" * 64,
    )
    changed = dict(verified)
    changed["verified_projection_digest"] = "c" * 64
    with pytest.raises(ValueError):
        plan_checkpoint_storage(
            [serialize_checkpoint(verified)], changed
        )


def test_invalid_state_rejected():
    checkpoint = make_checkpoint()
    checkpoint["state"] = "UNKNOWN"
    with pytest.raises(ValueError):
        serialize_checkpoint(checkpoint)
