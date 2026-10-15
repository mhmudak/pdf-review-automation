from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RegistryEntry:
    file_id: str
    name: str = ""
    modified_time: str = ""
    size: int = 0
    sha256: str = ""
    status: str = ""


def build_registry(
    values: list[list[Any]],
) -> tuple[
    dict[str, RegistryEntry],
    dict[str, RegistryEntry],
]:
    """Return latest entries by Drive file ID and PDF SHA256.

    _Files is append-only, so later rows win.
    """

    by_id: dict[str, RegistryEntry] = {}
    by_sha256: dict[str, RegistryEntry] = {}

    for row in values[1:]:

        padded = list(row) + [""] * max(
            0,
            16 - len(row),
        )

        file_id = str(
            padded[0]
        ).strip()

        if not file_id:
            continue

        entry = RegistryEntry(
            file_id=file_id,
            name=str(padded[1]),
            modified_time=str(padded[3]),
            size=(
                int(float(padded[4]))
                if str(padded[4]).strip()
                else 0
            ),
            sha256=str(padded[5]).strip(),
            status=str(padded[7]).strip(),
        )

        by_id[file_id] = entry

        if entry.sha256:
            by_sha256[entry.sha256] = entry

    return by_id, by_sha256


def precheck(
    file_meta,
    by_id: dict[str, RegistryEntry],
) -> tuple[str, str]:

    existing = by_id.get(
        file_meta.file_id
    )

    if (
        existing
        and existing.modified_time
        == file_meta.modified_time
        and existing.size
        == file_meta.size
    ):
        status = str(existing.status or "").strip().upper()

        # Metadata equality is not evidence that processing
        # completed. Failed or incomplete files must be retried.
        if status in {"PROCESSED", "DUPLICATE"}:
            return (
                "SKIP_UNCHANGED",
                "same successfully recorded Drive file "
                "ID, modifiedTime and size",
            )

        return (
            "PROCESS",
            "previous file status is not successfully completed: "
            + (status or "UNKNOWN"),
        )

    return "PROCESS", ""


def hash_precheck(
    sha256: str,
    file_id: str,
    by_sha256: dict[str, RegistryEntry],
) -> tuple[str, str]:

    if not sha256:
        return "PROCESS", ""

    duplicate = by_sha256.get(
        sha256
    )

    if (
        duplicate
        and duplicate.file_id
        != file_id
    ):
        return (
            "SKIP_DUPLICATE_FILE",
            f"same PDF SHA256 as {duplicate.file_id}",
        )

    return "PROCESS", ""