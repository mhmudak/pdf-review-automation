from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class BackendSnapshot:
    documents: list[dict[str, Any]]
    files: list[dict[str, Any]]
    entries: list[dict[str, Any]]
    author_rules: list[dict[str, Any]]

    def __post_init__(self) -> None:
        self._documents_by_key = {
            str(row.get("Document Key", "")).strip(): row
            for row in self.documents
            if str(row.get("Document Key", "")).strip()
        }

        self._entries_by_document: dict[
            str,
            list[dict[str, Any]],
        ] = {}

        self._entries_by_key: dict[
            tuple[str, str],
            dict[str, Any],
        ] = {}

        self._entries_by_id: dict[
            str,
            list[dict[str, Any]],
        ] = {}

        for row in self.entries:
            document_key = str(
                row.get("Document Key", "")
            ).strip()

            entry_id = str(
                row.get("Entry ID", "")
            ).strip()

            if document_key:
                self._entries_by_document.setdefault(
                    document_key,
                    [],
                ).append(row)

            if not entry_id:
                continue

            if document_key:
                key = (
                    document_key,
                    entry_id,
                )

                if key in self._entries_by_key:
                    raise ValueError(
                        "Duplicate canonical entry "
                        f"for {document_key!r} / "
                        f"{entry_id!r}"
                    )

                self._entries_by_key[
                    key
                ] = row

            self._entries_by_id.setdefault(
                entry_id,
                [],
            ).append(row)

        self._files_by_sha: dict[
            tuple[str, str],
            list[dict[str, Any]],
        ] = {}

        for row in self.files:
            document_key = str(
                row.get("Document Key", "")
            ).strip()

            sha = str(
                row.get("SHA256", "")
            ).strip().lower()

            if document_key and sha:
                self._files_by_sha.setdefault(
                    (document_key, sha),
                    [],
                ).append(row)

    def document(
        self,
        document_key: str,
    ) -> dict[str, Any] | None:
        return self._documents_by_key.get(
            str(document_key).strip()
        )

    def entries_for_document(
        self,
        document_key: str,
    ) -> list[dict[str, Any]]:
        return list(
            self._entries_by_document.get(
                str(document_key).strip(),
                [],
            )
        )

    def entry_for_document(
        self,
        document_key: str,
        entry_id: str,
    ) -> dict[str, Any] | None:
        return self._entries_by_key.get(
            (
                str(document_key).strip(),
                str(entry_id).strip(),
            )
        )

    def entry(
        self,
        entry_id: str,
    ) -> dict[str, Any] | None:
        """
        Backward-compatible lookup.

        If the same Entry ID exists in more than one
        document, fail closed instead of guessing.
        """

        matches = self._entries_by_id.get(
            str(entry_id).strip(),
            [],
        )

        if not matches:
            return None

        if len(matches) > 1:
            raise ValueError(
                "Entry ID is ambiguous across "
                "documents; use "
                "entry_for_document()."
            )

        return matches[0]

    def sha_known(
        self,
        document_key: str,
        sha256: str,
    ) -> bool:
        key = (
            str(document_key).strip(),
            str(sha256).strip().lower(),
        )

        return bool(
            self._files_by_sha.get(key)
        )


def rows_to_dicts(
    values: list[list[Any]],
) -> list[dict[str, Any]]:
    """
    Convert a Google Sheets values matrix into dictionaries
    using the first row as headers.
    """

    if not values:
        return []

    headers = [
        str(value).strip()
        for value in values[0]
    ]

    if not any(headers):
        return []

    output: list[
        dict[str, Any]
    ] = []

    for row in values[1:]:
        if not any(
            str(value).strip()
            for value in row
        ):
            continue

        item = {}

        for index, header in enumerate(
            headers
        ):
            if not header:
                continue

            item[header] = (
                row[index]
                if index < len(row)
                else ""
            )

        output.append(item)

    return output


def snapshot_from_batch_values(
    batch: dict[
        str,
        list[list[Any]],
    ],
) -> BackendSnapshot:
    """
    Build the in-memory backend snapshot from one batchGet
    response.
    """

    return BackendSnapshot(
        documents=rows_to_dicts(
            batch.get(
                "_Documents",
                [],
            )
        ),
        files=rows_to_dicts(
            batch.get(
                "_Files",
                [],
            )
        ),
        entries=rows_to_dicts(
            batch.get(
                "_Entries_V2",
                [],
            )
        ),
        author_rules=rows_to_dicts(
            batch.get(
                "_Author Rules",
                [],
            )
        ),
    )
