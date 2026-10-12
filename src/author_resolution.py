from __future__ import annotations

from dataclasses import dataclass
from typing import Any


GENERIC_RAW_AUTHORS = {
    "",
    "user",
    "reviewer",
    "author",
    "unknown",
    "anonymous",
    "admin",
}


def normalize_raw_author(value: Any) -> str:
    """
    Case-insensitive normalization used for classification
    and distinctive aliases.
    """
    return " ".join(
        str(value or "").split()
    ).casefold()


def normalize_raw_author_exact(value: Any) -> str:
    """
    Preserve case while normalizing surrounding/internal
    whitespace.

    This is essential for generic PDF identities because
    'User' and 'user' may represent different real people.
    """
    return " ".join(
        str(value or "").split()
    )


def raw_author_matches(
    expected: Any,
    actual: Any,
) -> bool:
    """
    Generic Acrobat identities are matched case-sensitively.
    Distinctive aliases may be matched case-insensitively.
    """
    expected_exact = normalize_raw_author_exact(expected)
    actual_exact = normalize_raw_author_exact(actual)

    expected_generic = is_generic_raw_author(expected_exact)
    actual_generic = is_generic_raw_author(actual_exact)

    if expected_generic or actual_generic:
        return expected_exact == actual_exact

    return (
        normalize_raw_author(expected_exact)
        == normalize_raw_author(actual_exact)
    )


def is_generic_raw_author(value: Any) -> bool:
    return (
        normalize_raw_author(value)
        in GENERIC_RAW_AUTHORS
    )


@dataclass(frozen=True)
class AuthorRule:
    rule_id: str
    scope: str
    canonical_author: str
    raw_author: str = ""
    document_key: str = ""
    version_id: str = ""
    root_entry_id: str = ""
    entry_id: str = ""
    status: str = "APPROVED"


@dataclass(frozen=True)
class AuthorResolution:
    canonical_author: str
    status: str
    method: str
    rule_id: str = ""


def _rule_matches(
    rule: AuthorRule,
    entry: dict[str, Any],
) -> bool:

    if rule.status != "APPROVED":
        return False

    raw = entry.get("raw_author", "")
    rule_raw = rule.raw_author

    if rule.scope == "ENTRY":
        return (
            bool(rule.entry_id)
            and rule.entry_id
            == str(
                entry.get("entry_id", "")
            )
        )

    if rule.scope == "THREAD":
        return (
            bool(rule.root_entry_id)
            and rule.root_entry_id
            == str(
                entry.get(
                    "root_entry_id",
                    "",
                )
            )
            and (
                not normalize_raw_author_exact(rule_raw)
                or raw_author_matches(
                    rule_raw,
                    raw,
                )
            )
        )

    if rule.scope == "VERSION":
        return (
            bool(rule.version_id)
            and rule.version_id
            == str(
                entry.get(
                    "version_id",
                    "",
                )
            )
            and raw_author_matches(
                rule_raw,
                raw,
            )
        )

    if rule.scope == "DOCUMENT_RAW":
        return (
            bool(rule.document_key)
            and rule.document_key
            == str(
                entry.get(
                    "document_key",
                    "",
                )
            )
            and raw_author_matches(
                rule_raw,
                raw,
            )
        )

    if rule.scope == "GLOBAL_ALIAS":
        return (
            bool(rule_raw)
            and raw_author_matches(
                rule_raw,
                raw,
            )
            and not is_generic_raw_author(
                raw
            )
        )

    return False


_RULE_PRIORITY = {
    "ENTRY": 500,
    "THREAD": 400,
    "VERSION": 300,
    "DOCUMENT_RAW": 200,
    "GLOBAL_ALIAS": 100,
}


def resolve_author(
    entry: dict[str, Any],
    rules: list[AuthorRule],
    historical_author_by_entry_id: (
        dict[str, str] | None
    ) = None,
) -> AuthorResolution:

    historical_author_by_entry_id = (
        historical_author_by_entry_id
        or {}
    )

    entry_id = str(
        entry.get("entry_id", "")
    ).strip()

    # ---------------------------------------------------------
    # 1. Exact historical native-ID provenance
    # ---------------------------------------------------------

    historical = str(
        historical_author_by_entry_id.get(
            entry_id,
            "",
        )
    ).strip()

    if historical:
        return AuthorResolution(
            canonical_author=historical,
            status="RESOLVED",
            method="HISTORICAL_NATIVE_ID",
        )

    # ---------------------------------------------------------
    # 2. Approved rules, narrowest first
    # ---------------------------------------------------------

    matching = [
        rule
        for rule in rules
        if _rule_matches(
            rule,
            entry,
        )
    ]

    if matching:
        matching.sort(
            key=lambda rule: (
                _RULE_PRIORITY.get(
                    rule.scope,
                    0,
                )
            ),
            reverse=True,
        )

        winner = matching[0]

        return AuthorResolution(
            canonical_author=(
                winner.canonical_author
            ),
            status="RESOLVED",
            method=winner.scope,
            rule_id=winner.rule_id,
        )

    # ---------------------------------------------------------
    # 3. Distinctive raw author can remain its own candidate,
    #    but is NOT automatically converted to a real name.
    # ---------------------------------------------------------

    raw = str(
        entry.get("raw_author", "")
    ).strip()

    if (
        raw
        and not is_generic_raw_author(raw)
    ):
        return AuthorResolution(
            canonical_author="",
            status="UNRESOLVED",
            method="DISTINCTIVE_RAW_UNMAPPED",
        )

    # ---------------------------------------------------------
    # 4. Generic User/user remains unresolved.
    # ---------------------------------------------------------

    return AuthorResolution(
        canonical_author="",
        status="UNRESOLVED",
        method="GENERIC_RAW_UNRESOLVED",
    )