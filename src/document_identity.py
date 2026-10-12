from __future__ import annotations

import os
from typing import Any

from versioning import normalize_document_key


def resolve_document_key(
    config: dict[str, Any],
) -> str:
    """
    Resolve the logical document identity.

    Do not infer version identity from filenames.
    A renamed or edited copy must remain the same
    logical document.
    """

    raw = (
        os.getenv(
            "WORKFLOW2_DOCUMENT_KEY",
            "",
        ).strip()
        or str(
            config.get(
                "document_key",
                "",
            )
        ).strip()
    )

    if not raw:
        raise ValueError(
            "Logical document key is required. "
            "Set WORKFLOW2_DOCUMENT_KEY or "
            "config['document_key']."
        )

    document_key = normalize_document_key(
        raw
    )

    if not document_key:
        raise ValueError(
            "Logical document key normalized "
            "to an empty value."
        )

    return document_key
