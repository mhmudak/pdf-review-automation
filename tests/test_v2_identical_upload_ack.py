from types import SimpleNamespace

from v2_pipeline_notifications import verified_identical_upload_ack


SHA = "a" * 64


def existing():
    return SimpleNamespace(file_id="old-drive-id", sha256=SHA)


def route(verified=True, export_id="export-001"):
    return {
        "pm_export_result": {
            "verified": verified,
            "export_id": export_id,
        }
    }


def decide(**overrides):
    params = {
        "file_id": "new-drive-id",
        "sha256": SHA,
        "previous_file": None,
        "matching_file": existing(),
        "route_result": route(),
    }
    params.update(overrides)
    return verified_identical_upload_ack(**params)


def test_new_drive_id_identical_content_acknowledged():
    alert = decide()
    assert alert["code"] == "IDENTICAL_UPLOAD_ACKNOWLEDGED"
    assert alert["audience"] == ["PM"]


def test_existing_drive_file_cannot_create_new_upload_ack():
    assert decide(previous_file=existing()) is None


def test_unknown_content_cannot_create_identical_ack():
    assert decide(matching_file=None) is None


def test_same_file_id_not_treated_as_new_upload():
    matching = SimpleNamespace(
        file_id="new-drive-id", sha256=SHA
    )
    assert decide(matching_file=matching) is None


def test_different_content_cannot_create_identical_ack():
    assert decide(sha256="b" * 64) is None


def test_unverified_export_blocks_acknowledgment():
    assert decide(route_result=route(False)) is None


def test_missing_export_id_blocks_acknowledgment():
    assert decide(route_result=route(True, "")) is None


def test_missing_export_record_blocks_acknowledgment():
    assert decide(route_result={}) is None
