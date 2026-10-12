from author_resolution import (
    AuthorRule,
    is_generic_raw_author,
    normalize_raw_author,
    resolve_author,
)


def test_raw_author_normalization():
    assert (
        normalize_raw_author(" User ")
        == "user"
    )


def test_user_is_generic():
    assert is_generic_raw_author(
        "User"
    )

    assert is_generic_raw_author(
        "user"
    )


def test_distinctive_alias_is_not_generic():
    assert not is_generic_raw_author(
        "Elamrityo"
    )


def test_historical_native_id_wins():
    entry = {
        "entry_id": "abc-123",
        "raw_author": "User",
        "document_key": "DOC1",
    }

    result = resolve_author(
        entry,
        [],
        {
            "abc-123": "Hala Afifi",
        },
    )

    assert (
        result.canonical_author
        == "Hala Afifi"
    )

    assert (
        result.method
        == "HISTORICAL_NATIVE_ID"
    )


def test_entry_override_resolves_generic_user():
    entry = {
        "entry_id": "reply-123",
        "raw_author": "User",
        "document_key": "DOC1",
        "version_id": "V2",
    }

    rules = [
        AuthorRule(
            rule_id="RULE-1",
            scope="ENTRY",
            entry_id="reply-123",
            raw_author="User",
            canonical_author=(
                "Faten Khalifeh"
            ),
        )
    ]

    result = resolve_author(
        entry,
        rules,
    )

    assert (
        result.canonical_author
        == "Faten Khalifeh"
    )

    assert result.status == "RESOLVED"


def test_global_generic_user_rule_is_not_applied():
    entry = {
        "entry_id": "reply-999",
        "raw_author": "User",
        "document_key": "DOC1",
    }

    rules = [
        AuthorRule(
            rule_id="BAD-RULE",
            scope="GLOBAL_ALIAS",
            raw_author="User",
            canonical_author=(
                "Faten Khalifeh"
            ),
        )
    ]

    result = resolve_author(
        entry,
        rules,
    )

    assert result.status == "UNRESOLVED"

    assert (
        result.method
        == "GENERIC_RAW_UNRESOLVED"
    )


def test_distinctive_global_alias_can_resolve():
    entry = {
        "entry_id": "x",
        "raw_author": "Elamrityo",
    }

    rules = [
        AuthorRule(
            rule_id="RULE-OSAMA",
            scope="GLOBAL_ALIAS",
            raw_author="Elamrityo",
            canonical_author=(
                "Osama Elamrety"
            ),
        )
    ]

    result = resolve_author(
        entry,
        rules,
    )

    assert (
        result.canonical_author
        == "Osama Elamrety"
    )


def test_entry_rule_beats_broader_document_rule():
    entry = {
        "entry_id": "reply-1",
        "raw_author": "User",
        "document_key": "DOC1",
    }

    rules = [
        AuthorRule(
            rule_id="DOCUMENT-RULE",
            scope="DOCUMENT_RAW",
            document_key="DOC1",
            raw_author="User",
            canonical_author="Reviewer A",
        ),
        AuthorRule(
            rule_id="ENTRY-RULE",
            scope="ENTRY",
            entry_id="reply-1",
            raw_author="User",
            canonical_author="Reviewer B",
        ),
    ]

    result = resolve_author(
        entry,
        rules,
    )

    assert (
        result.canonical_author
        == "Reviewer B"
    )

    assert (
        result.rule_id
        == "ENTRY-RULE"
    )

def test_version_rule_distinguishes_User_from_user():
    rule = AuthorRule(
        rule_id="FATEN-VERSION",
        scope="VERSION",
        version_id="V1",
        raw_author="User",
        canonical_author="Faten Khalifeh",
    )

    upper_entry = {
        "entry_id": "A",
        "version_id": "V1",
        "raw_author": "User",
    }

    lower_entry = {
        "entry_id": "B",
        "version_id": "V1",
        "raw_author": "user",
    }

    upper_result = resolve_author(
        upper_entry,
        [rule],
    )

    lower_result = resolve_author(
        lower_entry,
        [rule],
    )

    assert (
        upper_result.canonical_author
        == "Faten Khalifeh"
    )

    assert (
        lower_result.status
        == "UNRESOLVED"
    )


def test_distinctive_alias_remains_case_insensitive():
    rule = AuthorRule(
        rule_id="EMAN",
        scope="GLOBAL_ALIAS",
        raw_author="emanz",
        canonical_author="Eman Zahran",
    )

    result = resolve_author(
        {
            "entry_id": "A",
            "raw_author": "EMANZ",
        },
        [rule],
    )

    assert (
        result.canonical_author
        == "Eman Zahran"
    )
