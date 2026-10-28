import pytest

from v2_pm_export_coordinator import validate_recovery_versions


DOC = "IGCSE_ARABIC_2P"
VERSION = "IGCSE_ARABIC_2P@abc"
SHA = "a" * 64


def document(version=VERSION, sha=SHA):
    return {
        "Document Key": DOC,
        "Current Version ID": version,
        "Current PDF SHA256": sha,
    }


def pending(version=VERSION, sha=SHA):
    return {
        "document_key": DOC,
        "version_id": version,
        "pdf_sha256": sha,
    }


def test_valid_recovery_version():
    assert validate_recovery_versions(
        [pending()], [document()]
    ) == 1


def test_recovery_rejects_wrong_pdf_version():
    with pytest.raises(
        RuntimeError, match="BACKEND_VERSION_CONFLICT"
    ):
        validate_recovery_versions(
            [pending(version="old-version")],
            [document()],
        )


def test_recovery_rejects_wrong_pdf_sha():
    with pytest.raises(
        RuntimeError, match="BACKEND_VERSION_CONFLICT"
    ):
        validate_recovery_versions(
            [pending(sha="b" * 64)],
            [document()],
        )


def test_recovery_rejects_missing_document():
    with pytest.raises(
        RuntimeError, match="DOCUMENT_NOT_FOUND"
    ):
        validate_recovery_versions([pending()], [])


def test_recovery_rejects_multiple_pending_same_document():
    with pytest.raises(
        RuntimeError, match="MULTIPLE_PENDING_EXPORTS"
    ):
        validate_recovery_versions(
            [pending(), pending()],
            [document()],
        )


def test_recovery_rejects_duplicate_document_registry():
    with pytest.raises(
        RuntimeError, match="INVALID_BACKEND_DOCUMENT_REGISTRY"
    ):
        validate_recovery_versions(
            [pending()],
            [document(), document()],
        )
