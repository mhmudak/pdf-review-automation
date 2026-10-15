from types import SimpleNamespace

from registry import (
    RegistryEntry,
    build_registry,
    hash_precheck,
    precheck,
)


def test_build_registry_uses_correct_files_columns():
    values = [
        [
            "Drive File ID",
            "PDF Name",
            "Drive Link",
            "Modified Time",
            "Size Bytes",
            "PDF SHA256",
            "Reviewer",
            "Status",
            "Pages",
            "Annotations Found",
            "New",
            "Updated",
            "Unchanged",
            "Skipped Empty",
            "Processed At",
            "Message / Error",
        ],
        [
            "file-1",
            "book.pdf",
            "https://example.com",
            "2026-10-09T10:00:00Z",
            "12345",
            "abc123",
            "Reviewer Name",
            "PROCESSED",
            "323",
            "10",
            "10",
            "0",
            "0",
            "0",
            "timestamp",
            "",
        ],
    ]

    by_id, by_sha256 = build_registry(values)

    entry = by_id["file-1"]

    assert entry.sha256 == "abc123"
    assert entry.status == "PROCESSED"
    assert entry.size == 12345
    assert by_sha256["abc123"].file_id == "file-1"


def test_precheck_skips_unchanged_drive_file():
    by_id = {
        "file-1": RegistryEntry(
            file_id="file-1",
            modified_time="2026-10-09T10:00:00Z",
            size=100,
        status="PROCESSED", )
    }

    file_meta = SimpleNamespace(
        file_id="file-1",
        modified_time="2026-10-09T10:00:00Z",
        size=100,
    )

    action, _ = precheck(
        file_meta,
        by_id,
    )

    assert action == "SKIP_UNCHANGED"


def test_hash_precheck_detects_duplicate_different_drive_id():
    by_sha256 = {
        "samehash": RegistryEntry(
            file_id="original-id",
            sha256="samehash",
            status="PROCESSED",
        )
    }

    action, reason = hash_precheck(
        "samehash",
        "new-id",
        by_sha256,
    )

    assert action == "SKIP_DUPLICATE_FILE"
    assert "original-id" in reason


def test_hash_precheck_allows_same_drive_id():
    by_sha256 = {
        "samehash": RegistryEntry(
            file_id="same-id",
            sha256="samehash",
        )
    }

    action, _ = hash_precheck(
        "samehash",
        "same-id",
        by_sha256,
    )

    assert action == "PROCESS"