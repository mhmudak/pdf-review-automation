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

        self._entries_by_id: dict[
            str,
            dict[str, Any],
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

            if entry_id:
                self._entries_by_id[
                    entry_id
                ] = row

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

    def entry(
        self,
        entry_id: str,
    ) -> dict[str, Any] | None:
        return self._entries_by_id.get(
            str(entry_id).strip()
        )

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
