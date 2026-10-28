import pytest

from v2_notification_policy import (
    decide_notification,
    delivery_plan,
)


def intent(kind="IDENTICAL_UPLOAD", **kwargs):
    return decide_notification(
        event_kind=kind,
        document_key="TEST_DOC",
        event_id="upload-001",
        **kwargs,
    )


def test_unchanged_scheduler_poll_is_silent():
    result = intent("SCHEDULED_NO_CHANGE")
    assert result["notify"] is False


def test_identical_new_upload_is_acknowledged():
    result = intent()
    assert result["notify"] is True
    assert result["audience"] == ["PM"]


def test_same_event_has_stable_key():
    assert intent()["key"] == intent()["key"]


def test_distinct_uploads_have_distinct_keys():
    first = intent()["key"]
    second = decide_notification(
        event_kind="IDENTICAL_UPLOAD",
        document_key="TEST_DOC",
        event_id="upload-002",
    )["key"]
    assert first != second


def test_unverified_export_cannot_notify_pm():
    with pytest.raises(ValueError, match="verified export"):
        intent("EXPORT_COMPLETED", export_id="export-1")


def test_verified_export_can_notify_pm():
    result = intent(
        "EXPORT_COMPLETED",
        export_verified=True,
        export_id="export-1",
    )
    assert result["audience"] == ["PM"]


def test_test_mode_routes_only_to_admin():
    result = delivery_plan(
        intent(),
        mode="TEST",
        admin_email="admin@example.com",
        pm_email="pm@example.com",
    )
    assert result["recipients"] == ["admin@example.com"]
    assert result["subject_prefix"] == "[TEST]"


def test_final_mode_blocks_unauthorized_pm_delivery():
    with pytest.raises(RuntimeError, match="NOT_AUTHORIZED"):
        delivery_plan(
            intent(),
            mode="FINAL",
            pm_email="pm@example.com",
        )


def test_final_mode_requires_explicit_authorization():
    result = delivery_plan(
        intent(),
        mode="FINAL",
        pm_email="pm@example.com",
        admin_email="admin@example.com",
        pm_final_test_authorized=True,
    )
    assert result["recipients"] == ["pm@example.com", "admin@example.com"]
    assert result["subject_prefix"] == "[FINAL TEST]"


def test_failure_goes_to_admin():
    result = intent("EXPORT_FAILED", error="Verification failed")
    plan = delivery_plan(
        result,
        mode="PRODUCTION",
        admin_email="admin@example.com",
        pm_email="pm@example.com",
    )
    assert plan["recipients"] == ["admin@example.com"]


def test_missing_admin_email_fails_explicitly():
    with pytest.raises(RuntimeError, match="ADMIN_EMAIL_REQUIRED"):
        delivery_plan(intent(), mode="TEST")


def test_off_mode_never_sends():
    assert delivery_plan(intent(), mode="OFF")["send"] is False


def test_review_requires_verified_export():
    with pytest.raises(ValueError, match="verified export"):
        intent("REVIEW_REQUIRED")


def test_unknown_event_is_rejected():
    with pytest.raises(ValueError, match="Unknown"):
        intent("UNEXPECTED")
