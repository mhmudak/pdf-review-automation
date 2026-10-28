from copy import deepcopy

import pytest

from v2_pm_checkpoint import (
    new_export_checkpoint,
    advance_checkpoint,
    recover_after_interruption,
)


SHA = "a" * 64
VERIFICATION = "b" * 64


def checkpoint(**overrides):
    values = dict(
        document_key="IGCSE_ARABIC_2P",
        version_id="v2",
        pdf_sha256=SHA,
        output_spreadsheet_id="pm-sheet",
        output_tab="Trial PDF - All Data",
        previous_exported_version_id="v1",
    )
    values.update(overrides)
    return new_export_checkpoint(**values)


def test_new_checkpoint_is_pending():
    c = checkpoint()
    assert c["state"] == "EXPORT_PENDING"
    assert c["attempts"] == 0


def test_export_identity_is_deterministic():
    assert checkpoint()["export_id"] == checkpoint()["export_id"]


def test_different_version_has_different_identity():
    assert checkpoint()["export_id"] != checkpoint(
        version_id="v3"
    )["export_id"]


def test_different_destination_has_different_identity():
    assert checkpoint()["export_id"] != checkpoint(
        output_tab="Another Tab"
    )["export_id"]


def test_reject_invalid_sha():
    with pytest.raises(ValueError):
        checkpoint(pdf_sha256="invalid")


def test_cannot_use_pending_version_as_baseline():
    with pytest.raises(ValueError):
        checkpoint(previous_exported_version_id="v2")


def test_start_export_increments_attempts():
    c = advance_checkpoint(checkpoint(), "START_EXPORT")
    assert c["state"] == "EXPORTING"
    assert c["attempts"] == 1


def test_failed_export_is_retryable():
    c = advance_checkpoint(checkpoint(), "START_EXPORT")
    c = advance_checkpoint(c, "EXPORT_FAILED", error="API 429")
    assert c["state"] == "EXPORT_PENDING"
    assert recover_after_interruption(c)["next_action"] == (
        "VERIFY_DESTINATION_THEN_RESUME"
    )


def test_interrupted_export_requires_destination_verification():
    c = advance_checkpoint(checkpoint(), "START_EXPORT")
    assert recover_after_interruption(c)["next_action"] == (
        "VERIFY_DESTINATION_THEN_RESUME"
    )


def test_cannot_mark_verified_without_proof():
    c = advance_checkpoint(checkpoint(), "START_EXPORT")
    with pytest.raises(ValueError):
        advance_checkpoint(c, "EXPORT_VERIFIED")


def test_verified_export_may_be_completed_without_notification():
    c = advance_checkpoint(checkpoint(), "START_EXPORT")
    c = advance_checkpoint(
        c, "EXPORT_VERIFIED",
        verification_digest=VERIFICATION,
    )
    c = advance_checkpoint(
        c, "COMPLETE_WITHOUT_NOTIFICATION"
    )
    assert c["state"] == "COMPLETED"


def test_notification_requires_verified_export():
    with pytest.raises(ValueError):
        advance_checkpoint(checkpoint(), "QUEUE_NOTIFICATION")


def test_notification_completed_only_after_confirmation():
    c = advance_checkpoint(checkpoint(), "START_EXPORT")
    c = advance_checkpoint(
        c, "EXPORT_VERIFIED",
        verification_digest=VERIFICATION,
    )
    c = advance_checkpoint(c, "QUEUE_NOTIFICATION")
    assert c["state"] == "NOTIFICATION_PENDING"
    c = advance_checkpoint(c, "CONFIRM_DELIVERY")
    assert c["state"] == "COMPLETED"


def test_uncertain_email_delivery_is_not_automatically_retried():
    c = advance_checkpoint(checkpoint(), "START_EXPORT")
    c = advance_checkpoint(
        c, "EXPORT_VERIFIED",
        verification_digest=VERIFICATION,
    )
    c = advance_checkpoint(c, "QUEUE_NOTIFICATION")
    c = advance_checkpoint(c, "DELIVERY_UNCERTAIN")
    assert recover_after_interruption(c)["next_action"] == (
        "MANUAL_DELIVERY_REVIEW"
    )


def test_completed_export_cannot_restart():
    c = advance_checkpoint(checkpoint(), "START_EXPORT")
    c = advance_checkpoint(
        c, "EXPORT_VERIFIED",
        verification_digest=VERIFICATION,
    )
    c = advance_checkpoint(
        c, "COMPLETE_WITHOUT_NOTIFICATION"
    )
    with pytest.raises(ValueError):
        advance_checkpoint(c, "START_EXPORT")


def test_state_transition_does_not_mutate_original():
    original = checkpoint()
    before = deepcopy(original)
    advance_checkpoint(original, "START_EXPORT")
    assert original == before
