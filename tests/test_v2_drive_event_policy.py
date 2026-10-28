import pytest

from v2_drive_event_policy import observe_pdf


def pdf(
    file_id="file-1",
    modified="2026-10-15T10:00:00Z",
    checksum="abc123",
):
    return {
        "id": file_id,
        "modifiedTime": modified,
        "md5Checksum": checksum,
        "mimeType": "application/pdf",
    }


def test_initial_baseline_does_not_notify():
    result = observe_pdf(pdf(), initialized=False)
    assert result["action"] == "INITIAL_BASELINE"
    assert result["new_event"] is False


def test_new_file_after_baseline_is_an_event():
    result = observe_pdf(pdf(), initialized=True)
    assert result["action"] == "NEW_FILE_OBSERVED"
    assert result["new_event"] is True


def test_scheduler_recheck_is_silent():
    first = observe_pdf(pdf(), initialized=True)
    second = observe_pdf(
        pdf(), first["observation"], initialized=True
    )
    assert second["action"] == "NO_CHANGE"
    assert second["new_event"] is False


def test_replacement_of_identical_pdf_is_detected():
    first = observe_pdf(pdf(), initialized=True)
    second = observe_pdf(
        pdf(modified="2026-10-15T11:00:00Z"),
        first["observation"],
        initialized=True,
    )
    assert second["action"] == "FILE_MODIFIED"
    assert second["new_event"] is True


def test_new_content_checksum_is_detected():
    first = observe_pdf(pdf(), initialized=True)
    second = observe_pdf(
        pdf(checksum="different"),
        first["observation"],
        initialized=True,
    )
    assert second["new_event"] is True


def test_observation_token_is_stable():
    a = observe_pdf(pdf(), initialized=True)
    b = observe_pdf(pdf(), initialized=True)
    assert a["observation"]["event_id"] == (
        b["observation"]["event_id"]
    )


def test_other_file_observation_is_rejected():
    first = observe_pdf(pdf(), initialized=True)
    with pytest.raises(ValueError, match="another file"):
        observe_pdf(
            pdf(file_id="file-2"),
            first["observation"],
            initialized=True,
        )


def test_missing_identity_fails_closed():
    with pytest.raises(ValueError, match="required"):
        observe_pdf(
            {"id": "file-1", "mimeType": "application/pdf"},
            initialized=True,
        )


def test_non_pdf_is_rejected():
    with pytest.raises(ValueError, match="Only PDF"):
        observe_pdf(
            {**pdf(), "mimeType": "text/plain"},
            initialized=True,
        )
