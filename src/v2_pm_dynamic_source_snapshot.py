"""Read-only planning/validation for backward-compatible dynamic reply snapshots.

Legacy A:H source snapshots remain byte-for-byte compatible. New snapshots
extend Reply 1..N contiguously before Reply Entry IDs; row/snapshot digests
cover every reply and the ordered ID string. No Google I/O.
"""
from __future__ import annotations

import hashlib
import json
import re

_REPLY = re.compile(r"Reply ([1-9][0-9]*)\Z")


def _text(value):
    return "" if value is None else str(value)


def _digest(value):
    data = json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def headers_for_depth(depth):
    if depth < 3:
        raise ValueError("SNAPSHOT_REPLY_DEPTH_TOO_SMALL")
    return (["Root Entry ID", "Comment"]
            + [f"Reply {i}" for i in range(1, depth + 1)]
            + ["Reply Entry IDs", "Source Row Digest", "Snapshot ID"])


def validate_headers(headers):
    labels = [_text(x) for x in headers]
    if len(labels) < 8 or labels != headers_for_depth(len(labels) - 5):
        raise RuntimeError("SOURCE_SNAPSHOT_SCHEMA_CONFLICT")
    return len(labels) - 5


def create_table(rows):
    depth = 3
    seen = set()
    for row in rows:
        root = _text(row.get("Root Entry ID")).strip()
        if not root or root in seen:
            raise RuntimeError("SOURCE_SNAPSHOT_ID_CONFLICT")
        seen.add(root)
        used = [int(m.group(1)) for key, value in row.items()
                if (m := _REPLY.fullmatch(str(key))) and _text(value).strip()]
        if used and sorted(used) != list(range(1, max(used) + 1)):
            raise RuntimeError("SOURCE_REPLY_GAP")
        raw = _text(row.get("Reply Entry IDs"))
        reply_ids = [x.strip() for x in raw.replace("|", ",").split(",") if x.strip()]
        if len(reply_ids) != len(used) or len(reply_ids) != len(set(reply_ids)):
            raise RuntimeError("SOURCE_REPLY_ID_MISMATCH")
        depth = max(depth, max(used, default=0))
    headers = headers_for_depth(depth)
    fields = headers[:-2]
    records = []
    for row in sorted(rows, key=lambda x: _text(x.get("Root Entry ID"))):
        values = [_text(row.get(field)) for field in fields]
        # Canonicalize separators just as the original fixed-width table did.
        ids = [x.strip() for x in values[-1].replace("|", ",").split(",") if x.strip()]
        values[-1] = " | ".join(ids)
        records.append(values)
    marker = _digest(records)
    return [headers] + [[*values, _digest(values), marker] for values in records]


def read_table(raw):
    if not raw:
        raise RuntimeError("EMPTY_SOURCE_SNAPSHOT")
    validate_headers(raw[0])
    width = len(raw[0])
    body_width = width - 2
    records = []
    names = set()
    markers = set()
    for record in raw[1:]:
        if len(record) > width:
            raise RuntimeError("SOURCE_SNAPSHOT_SCHEMA_CONFLICT")
        values = list(record) + [""] * (width - len(record))
        if not values[0] or values[0] in names:
            raise RuntimeError("SOURCE_SNAPSHOT_ID_CONFLICT")
        names.add(values[0])
        if _digest(values[:body_width]) != values[-2]:
            raise RuntimeError("SOURCE_SNAPSHOT_ROW_TAMPERED")
        markers.add(values[-1])
        records.append(values)
    if not records:
        raise RuntimeError("EMPTY_SOURCE_SNAPSHOT")
    if len(markers) != 1 or _digest([v[:body_width] for v in records]) != next(iter(markers)):
        raise RuntimeError("SOURCE_SNAPSHOT_DIGEST_MISMATCH")
    return [dict(zip(raw[0][:body_width], v[:body_width])) for v in records]
