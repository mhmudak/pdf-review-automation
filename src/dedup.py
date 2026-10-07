#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

MUTABLE_FIELDS = {
    "comment",
    "selected_text",
    "subject",
    "modified",
    "annotation_type",
    "rect_x0",
    "rect_y0",
    "rect_x1",
    "rect_y1",
    "import_candidate",
    "skip_reason",
    "is_empty",
}


def load_rows(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_ledger(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return {row["identity_key"]: row for row in data}
    return data


def changed(old: dict[str, Any], new: dict[str, Any]) -> bool:
    return any(old.get(field) != new.get(field) for field in MUTABLE_FIELDS)


def upsert(rows: list[dict[str, Any]], ledger: dict[str, dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    result = {
        "inserted": 0,
        "updated": 0,
        "unchanged": 0,
        "skipped_non_candidate": 0,
        "inserted_keys": [],
        "updated_keys": [],
    }
    for row in rows:
        if not row.get("import_candidate", True):
            result["skipped_non_candidate"] += 1
            continue
        key = row["identity_key"]
        existing = ledger.get(key)
        if existing is None:
            ledger[key] = row
            result["inserted"] += 1
            result["inserted_keys"].append(key)
        elif changed(existing, row):
            # Preserve evidence/history fields from the newest source snapshot while
            # keeping the same logical identity key.
            ledger[key] = row
            result["updated"] += 1
            result["updated_keys"].append(key)
        else:
            result["unchanged"] += 1
    result["ledger_size"] = len(ledger)
    return ledger, result


def main() -> None:
    p = argparse.ArgumentParser(description="Workflow 2 annotation upsert / dedup engine")
    p.add_argument("annotations", type=Path)
    p.add_argument("--ledger", type=Path, required=True)
    args = p.parse_args()

    rows = load_rows(args.annotations)
    ledger = load_ledger(args.ledger)
    ledger, result = upsert(rows, ledger)
    args.ledger.parent.mkdir(parents=True, exist_ok=True)
    args.ledger.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
