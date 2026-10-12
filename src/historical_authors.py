from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def historical_map_path(
    config: dict[str, Any],
) -> Path | None:
    raw = (
        os.getenv(
            "WORKFLOW2_HISTORICAL_AUTHOR_MAP",
            "",
        ).strip()
        or str(
            config.get(
                "historical_author_map_path",
                "",
            )
        ).strip()
    )

    if not raw:
        return None

    path = Path(raw)

    if not path.is_absolute():
        path = (
            Path(__file__).resolve().parent
            / path
        )

    return path.resolve()


def load_historical_author_map(
    config: dict[str, Any],
) -> dict[str, str]:
    """
    Load exact native Entry ID -> canonical author
    provenance.

    No fuzzy matching and no raw-author inference.
    """

    path = historical_map_path(config)

    if path is None:
        return {}

    if not path.exists():
        raise FileNotFoundError(
            f"Historical author map not found: {path}"
        )

    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if isinstance(payload, dict) and (
        "entry_id_to_author" in payload
    ):
        payload = payload[
            "entry_id_to_author"
        ]

    if not isinstance(payload, dict):
        raise ValueError(
            "Historical author map must be "
            "a JSON object."
        )

    result: dict[str, str] = {}

    for raw_entry_id, raw_author in (
        payload.items()
    ):
        entry_id = str(
            raw_entry_id
        ).strip()

        canonical_author = str(
            raw_author
        ).strip()

        if not entry_id:
            raise ValueError(
                "Historical map contains "
                "an empty Entry ID."
            )

        if not canonical_author:
            raise ValueError(
                "Historical map contains "
                f"an empty author for {entry_id!r}."
            )

        result[entry_id] = (
            canonical_author
        )

    return result
