"""Detect unfinished PM exports from durable checkpoint storage."""

from v2_pm_checkpoint_adapter import read_checkpoint_table
from v2_pm_checkpoint_store import deserialize_checkpoint


def unfinished_pm_exports(sheets):
    """Return all exports requiring recovery or delivery review.

    A missing/malformed checkpoint tab raises an error:
    strict V2 mode must fail closed, not assume success.
    """
    rows = read_checkpoint_table(sheets)
    pending = []

    for row in rows:
        checkpoint = deserialize_checkpoint(row)
        if checkpoint["state"] != "COMPLETED":
            pending.append(checkpoint)

    return pending
