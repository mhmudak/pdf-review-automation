from types import SimpleNamespace

from registry import RegistryEntry, precheck


def file_meta(modified="2026-10-15T10:00:00Z"):
    return SimpleNamespace(
        file_id="drive-001",
        modified_time=modified,
        size=12345,
    )


def previous(status):
    return {
        "drive-001": RegistryEntry(
            file_id="drive-001",
            modified_time="2026-10-15T10:00:00Z",
            size=12345,
            status=status,
        )
    }


def test_processed_unchanged_pdf_is_skipped():
    action, _ = precheck(file_meta(), previous("PROCESSED"))
    assert action == "SKIP_UNCHANGED"


def test_duplicate_unchanged_pdf_is_skipped():
    action, _ = precheck(file_meta(), previous("DUPLICATE"))
    assert action == "SKIP_UNCHANGED"


def test_failed_pdf_is_retried():
    action, reason = precheck(file_meta(), previous("ERROR"))
    assert action == "PROCESS"
    assert "ERROR" in reason


def test_incomplete_pdf_is_retried():
    action, _ = precheck(file_meta(), previous("PROCESSING"))
    assert action == "PROCESS"


def test_unknown_status_is_retried():
    action, _ = precheck(file_meta(), previous(""))
    assert action == "PROCESS"


def test_changed_pdf_is_processed():
    action, _ = precheck(
        file_meta(modified="2026-10-15T11:00:00Z"),
        previous("PROCESSED"),
    )
    assert action == "PROCESS"


def test_new_pdf_is_processed():
    action, _ = precheck(file_meta(), {})
    assert action == "PROCESS"
