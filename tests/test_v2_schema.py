from sheets_adapter import (
    AUTHOR_RULE_HEADERS,
    DOCUMENT_HEADERS,
    ENTRY_HISTORY_HEADERS,
    ENTRY_V2_HEADERS,
)


def test_v2_schema_column_counts():
    assert len(DOCUMENT_HEADERS) == 10
    assert len(ENTRY_V2_HEADERS) == 35
    assert len(ENTRY_HISTORY_HEADERS) == 30
    assert len(AUTHOR_RULE_HEADERS) == 12


def test_v2_entry_schema_contains_signature():
    assert "Entry Signature" in ENTRY_V2_HEADERS

    assert (
        ENTRY_V2_HEADERS.index("Entry Signature")
        == ENTRY_V2_HEADERS.index("Entry ID") + 1
    )


def test_v2_entry_schema_supports_current_state():
    required = {
        "Document Key",
        "Version ID",
        "Entry ID",
        "Entry Signature",
        "Active",
        "Source State",
        "First Seen",
        "Last Seen",
    }

    assert required.issubset(
        set(ENTRY_V2_HEADERS)
    )


def test_entry_history_schema_supports_audit():
    required = {
        "History Key",
        "Document Key",
        "Version ID",
        "Entry ID",
        "Entry Signature",
        "Change Type",
        "Previous Signature",
        "Recorded At",
    }

    assert required.issubset(
        set(ENTRY_HISTORY_HEADERS)
    )


def test_author_rules_schema_is_complete():
    required = {
        "Rule ID",
        "Scope",
        "Document Key",
        "Version ID",
        "Root Entry ID",
        "Entry ID",
        "Raw Author",
        "Canonical Author",
        "Status",
        "Approved By",
        "Approved At",
        "Notes",
    }

    assert required == set(
        AUTHOR_RULE_HEADERS
    )
