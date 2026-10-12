import pytest

from document_identity import (
    resolve_document_key,
)


def test_document_key_from_config(
    monkeypatch,
):
    monkeypatch.delenv(
        "WORKFLOW2_DOCUMENT_KEY",
        raising=False,
    )

    result = resolve_document_key(
        {
            "document_key":
                "IGCSE_ARABIC_2P"
        }
    )

    assert result


def test_env_document_key_overrides_config(
    monkeypatch,
):
    monkeypatch.setenv(
        "WORKFLOW2_DOCUMENT_KEY",
        "CANONICAL_BOOK",
    )

    result = resolve_document_key(
        {
            "document_key":
                "OTHER_BOOK"
        }
    )

    assert result == "CANONICAL_BOOK"


def test_missing_document_key_fails_closed(
    monkeypatch,
):
    monkeypatch.delenv(
        "WORKFLOW2_DOCUMENT_KEY",
        raising=False,
    )

    with pytest.raises(
        ValueError,
        match="document key",
    ):
        resolve_document_key({})
