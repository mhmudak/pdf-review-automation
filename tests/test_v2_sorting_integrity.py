from v2_output_projection import (
    project_entries,
    reading_key,
    timestamp,
)


def root(entry_id, **extra):
    item = {
        "entry_id": entry_id,
        "relation_type": "ROOT",
        "book_page": "17",
        "pdf_page": 25,
        "comment": entry_id,
    }
    item.update(extra)
    return item


def test_timezone_offsets_represent_same_instant():
    assert timestamp("2026-10-13T12:00:00+03:00") == timestamp(
        "2026-10-13T09:00:00Z"
    )


def test_naive_dates_are_assumed_utc_for_sorting():
    assert timestamp("2026-10-13T09:00:00") == timestamp(
        "2026-10-13T09:00:00+00:00"
    )


def test_invalid_and_missing_dates_are_deterministic():
    assert timestamp("") == 0
    assert timestamp("not a date") == 0
    assert timestamp(None) == 0


def test_missing_coordinates_have_stable_entry_id_fallback():
    entries = [
        root("B", modified="invalid"),
        root("A", modified="invalid"),
    ]
    result = project_entries(entries)

    assert [
        row["Root Entry ID"] for row in result["rows"]
    ] == ["A", "B"]


def test_nonfinite_coordinates_are_not_valid_positions():
    entry = root(
        "BAD",
        rect_x0=float("nan"),
        rect_y0=float("inf"),
    )

    assert reading_key(entry)[2] == 1


def test_position_sorting_precedes_modified_timestamp():
    entries = [
        root(
            "LOW",
            rect_x0=100,
            rect_y0=300,
            modified="2020-01-01T00:00:00Z",
        ),
        root(
            "HIGH",
            rect_x0=100,
            rect_y0=100,
            modified="2026-10-13T00:00:00Z",
        ),
    ]

    result = project_entries(entries)

    assert [
        row["Root Entry ID"] for row in result["rows"]
    ] == ["HIGH", "LOW"]


def test_reply_order_follows_actual_instant():
    entries = [
        root("ROOT"),
        {
            "entry_id": "LATE",
            "relation_type": "REPLY",
            "parent_entry_id": "ROOT",
            "created": "2026-10-13T13:00:00+03:00",
            "comment": "Later reply",
        },
        {
            "entry_id": "EARLY",
            "relation_type": "REPLY",
            "parent_entry_id": "ROOT",
            "created": "2026-10-13T09:00:00Z",
            "comment": "Earlier reply",
        },
    ]

    result = project_entries(entries)

    assert result["rows"][0]["Reply Entry IDs"] == (
        "EARLY, LATE"
    )
