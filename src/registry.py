from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RegistryEntry:
    file_id: str
    name: str = ""
    modified_time: str = ""
    size: int = 0
    md5_checksum: str = ""
    sha256: str = ""
    status: str = ""


def build_registry(values: list[list[Any]]) -> tuple[dict[str, RegistryEntry], dict[str, RegistryEntry]]:
    """Return latest entries by Drive file ID and by MD5.

    _Files is append-only, so later rows win.
    """
    by_id: dict[str, RegistryEntry] = {}
    by_md5: dict[str, RegistryEntry] = {}
    for row in values[1:]:
        padded = list(row) + [""] * max(0, 17 - len(row))
        file_id = str(padded[0]).strip()
        if not file_id:
            continue
        entry = RegistryEntry(
            file_id=file_id,
            name=str(padded[1]),
            modified_time=str(padded[3]),
            size=int(float(padded[4])) if str(padded[4]).strip() else 0,
            md5_checksum=str(padded[5]),
            sha256=str(padded[6]),
            status=str(padded[8]),
        )
        by_id[file_id] = entry
        if entry.md5_checksum:
            by_md5[entry.md5_checksum] = entry
    return by_id, by_md5


def precheck(file_meta, by_id: dict[str, RegistryEntry], by_md5: dict[str, RegistryEntry]) -> tuple[str, str]:
    existing = by_id.get(file_meta.file_id)
    if existing and existing.modified_time == file_meta.modified_time and existing.size == file_meta.size:
        return "SKIP_UNCHANGED", "same Drive file ID, modifiedTime and size"
    if file_meta.md5_checksum:
        duplicate = by_md5.get(file_meta.md5_checksum)
        if duplicate and duplicate.file_id != file_meta.file_id:
            return "SKIP_DUPLICATE_FILE", f"same Drive MD5 as {duplicate.file_id}"
    return "PROCESS", ""
