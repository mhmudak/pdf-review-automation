"""Pure PM-facing projection of PDF annotation entries."""

from __future__ import annotations

from collections import defaultdict
import json
from datetime import datetime, timezone
import math
from typing import Any


BASE_HEADERS = [
    "Book Page", "PDF Page", "Author", "Last Modified",
    "Comment",
]

AFTER_REPLIES = [
    "Category", "Selected Text", "Annotation Type",
    "Root Entry ID", "Relation Type", "Parent Entry ID",
    "Group Entry IDs", "Group Parent Links", "Reply Entry IDs",
]


def page_key(value: Any) -> tuple[int, int, str]:
    """Roman preliminary pages precede numbered book pages."""
    value = str(value or "").strip().lower()
    if value.isdecimal():
        return (1, int(value), "")
    roman = {"i": 1, "v": 5, "x": 10,
             "l": 50, "c": 100, "d": 500, "m": 1000}
    if value and all(c in roman for c in value):
        total = 0
        for index, char in enumerate(value):
            number = roman[char]
            following = roman.get(value[index + 1], 0) \
                if index + 1 < len(value) else 0
            total += -number if number < following else number
        return (0, total, "")
    return (2, 0, value)


def timestamp(value: Any) -> float:
    """Deterministic UTC instant; naive ISO dates assume UTC."""
    text = str(value or "").strip()

    if not text:
        return 0.0

    try:
        dt = datetime.fromisoformat(
            text.replace("Z", "+00:00").replace("z", "+00:00")
        )

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.timestamp()

    except (ValueError, TypeError, OverflowError):
        return 0.0


def reading_key(
    entry: dict[str, Any],
    *,
    direction: str = "rtl",
    row_tolerance: float = 8.0,
) -> tuple:
    """Page ascending, then vertical and horizontal position."""
    if direction not in ("rtl", "ltr"):
        raise ValueError("direction must be rtl or ltr")
    if row_tolerance <= 0:
        raise ValueError("row_tolerance must be positive")

    def coordinate(name: str):
        try:
            value = entry.get(name)
            if value is None or str(value).strip() == "":
                return None
            number = float(value)
            return number if math.isfinite(number) else None
        except (ValueError, TypeError):
            return None

    y = coordinate("rect_y0")
    x = coordinate("rect_x0")
    position_known = y is not None and x is not None

    return (
        page_key(entry.get("book_page")),
        int(entry.get("pdf_page") or 0),
        0 if position_known else 1,
        round(y / row_tolerance) if position_known else 0,
        (-x if direction == "rtl" else x)
        if position_known else 0,
        timestamp(entry.get("modified") or entry.get("created")),
        str(entry.get("entry_id") or ""),
    )


def normalize_backend_entries(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert active V2 sheet records to projection entries."""
    import json
    import math

    mapping = {
        "Entry ID": "entry_id",
        "Parent Entry ID": "parent_entry_id",
        "Root Entry ID": "root_entry_id",
        "Relation Type": "relation_type",
        "Raw Author": "raw_author",
        "Canonical Author": "canonical_author",
        "PDF Page": "pdf_page",
        "Book Page": "book_page",
        "Annotation Type": "annotation_type",
        "Category": "category",
        "Content": "comment",
        "Selected Text": "selected_text",
        "Created Date": "created",
        "Modified Date": "modified",
        "XRef": "xref",
    }

    normalized = []

    for record in records:
        active = str(
            record.get("Active", True)
        ).strip().lower()

        if active in ("false", "0", "no"):
            continue

        entry = {
            target: record.get(source, "")
            for source, target in mapping.items()
        }

        coordinates = record.get("Coordinates", "")

        if coordinates:
            try:
                parsed = (
                    json.loads(coordinates)
                    if isinstance(coordinates, str)
                    else coordinates
                )

                if isinstance(parsed, dict):
                    names = (
                        "rect_x0", "rect_y0",
                        "rect_x1", "rect_y1",
                    )

                    values = {
                        name: float(parsed[name])
                        for name in names
                    }

                    if all(
                        math.isfinite(value)
                        for value in values.values()
                    ):
                        entry.update(values)

            except (
                ValueError, TypeError, KeyError,
                OverflowError,
            ):
                # Existing backend rows may have
                # missing or legacy coordinates.
                # Preserve the row for fallback sorting.
                pass

        normalized.append(entry)

    return normalized


def project_backend_rows(
    records: list[dict[str, Any]],
    *,
    direction: str = "rtl",
    minimum_reply_columns: int = 3,
) -> dict[str, Any]:
    """Project active backend rows into the PM view."""
    return project_entries(
        normalize_backend_entries(records),
        direction=direction,
        minimum_reply_columns=minimum_reply_columns,
    )


def project_entries(
    entries: list[dict[str, Any]],
    *,
    direction: str = "rtl",
    minimum_reply_columns: int = 3,
) -> dict[str, Any]:
    """Project all roots, replies and associated GROUP annotations.

    Raises on orphan replies rather than silently losing comments.
    GROUP annotations are retained in audit metadata, not reply cells.
    """
    if minimum_reply_columns < 0:
        raise ValueError("minimum_reply_columns cannot be negative")

    by_id = {}
    for entry in entries:
        entry_id = str(entry.get("entry_id") or "").strip()
        if not entry_id or entry_id in by_id:
            raise ValueError(f"missing or duplicate entry_id: {entry_id}")
        by_id[entry_id] = entry

    def find_root(entry: dict[str, Any]) -> str:
        current = entry
        visited = set()
        while current:
            current_id = str(current.get("entry_id") or "")
            if current_id in visited:
                return ""
            visited.add(current_id)

            relation = str(
                current.get("relation_type") or "ROOT"
            ).upper()
            if relation == "ROOT":
                return current_id

            parent_id = str(
                current.get("parent_entry_id") or ""
            ).strip()
            if not parent_id or parent_id not in by_id:
                # An orphan GROUP becomes a visible root.
                # Replies to that GROUP must remain attached.
                return current_id if relation == "GROUP" else ""

            current = by_id[parent_id]
        return ""

    roots = []
    replies = defaultdict(list)
    groups = defaultdict(list)
    orphan_groups = []
    orphan_replies = []

    for entry in entries:
        relation = str(
            entry.get("relation_type") or "ROOT"
        ).upper()
        if relation not in ("ROOT", "REPLY", "GROUP"):
            raise ValueError(f"unknown relation_type: {relation}")

        if relation == "ROOT":
            roots.append(entry)
            continue

        root_id = find_root(entry)

        if relation == "GROUP":
            # An orphan GROUP resolves to its own Entry ID.
            # It becomes a visible root, not a group of itself.
            if root_id and root_id != str(entry["entry_id"]):
                groups[root_id].append(entry)
            else:
                orphan_groups.append(entry)
        elif root_id:
            replies[root_id].append(entry)
        else:
            orphan_replies.append(entry)

    if orphan_replies:
        raise ValueError(
            f"{len(orphan_replies)} orphan replies; "
            "cannot safely project all conversations"
        )

    # GROUP annotations whose parent cannot be found
    # become independent visible rows. Linked GROUP
    # annotations remain attached as audit metadata.
    roots.extend(orphan_groups)

    maximum = max(
        (len(items) for items in replies.values()),
        default=0,
    )
    reply_count = max(minimum_reply_columns, maximum)

    headers = (
        BASE_HEADERS
        + [f"Reply {n}" for n in range(1, reply_count + 1)]
        + AFTER_REPLIES
    )

    roots.sort(key=lambda item: reading_key(
        item, direction=direction
    ))

    output = []
    for root in roots:
        root_id = str(root["entry_id"])
        thread = sorted(
            replies[root_id],
            key=lambda item: (
                timestamp(item.get("created") or item.get("modified")),
                str(item.get("entry_id") or ""),
            ),
        )
        associated = sorted(
            groups[root_id],
            key=lambda item: str(item.get("entry_id") or ""),
        )

        row = {
            "Book Page": root.get("book_page", ""),
            "PDF Page": root.get("pdf_page", ""),
            "Author": (
                root.get("canonical_author")
                or root.get("reviewer")
                or root.get("raw_author", "")
            ),
            "Last Modified": root.get("modified", ""),
            "Comment": root.get("comment", ""),
            "Category": root.get("category", ""),
            "Selected Text": root.get("selected_text", ""),
            "Annotation Type": root.get("annotation_type", ""),
            "Root Entry ID": root_id,
            "Relation Type": str(
                root.get("relation_type") or "ROOT"
            ).upper(),
            "Parent Entry ID": str(
                root.get("parent_entry_id") or ""
            ),
            "Group Parent Links": json.dumps(
                [
                    {
                        "entry_id": str(item["entry_id"]),
                        "parent_entry_id": str(
                            item.get("parent_entry_id") or ""
                        ),
                        "relation_type": str(
                            item.get("relation_type") or "GROUP"
                        ).upper(),
                    }
                    for item in associated
                ],
                ensure_ascii=False,
                sort_keys=True,
            ),
            "Group Entry IDs": ", ".join(
                str(item["entry_id"]) for item in associated
            ),
            "Reply Entry IDs": ", ".join(
                str(item["entry_id"]) for item in thread
            ),
        }

        for n, reply in enumerate(thread, 1):
            author = (
                reply.get("canonical_author")
                or reply.get("reviewer")
                or reply.get("raw_author")
                or ""
            )
            content = str(reply.get("comment") or "")
            modified = str(reply.get("modified") or "")
            row[f"Reply {n}"] = (
                f"{author} ? {content}\n\n{modified}"
            )

        output.append(row)

    return {
        "headers": headers,
        "rows": output,
        "reply_columns": reply_count,
        "orphan_groups": orphan_groups,
        "group_count": sum(map(len, groups.values()))
                       + len(orphan_groups),
        "root_count": len(roots),
        "reply_count": sum(map(len, replies.values())),
    }
