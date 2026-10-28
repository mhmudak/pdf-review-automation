import json

from v2_model import prepare_v2_entries
from v2_mutations import _canonical_entry
from v2_output_projection import project_backend_rows


def test_coordinates_survive_full_v2_projection():
    source_entries = [
        {
            "entry_id": "LEFT",
            "relation_type": "ROOT",
            "raw_author": "Reviewer",
            "pdf_page": 25,
            "book_page": "17",
            "comment": "Left annotation",
            "rect_x0": 100,
            "rect_y0": 200,
            "rect_x1": 150,
            "rect_y1": 220,
        },
        {
            "entry_id": "RIGHT",
            "relation_type": "ROOT",
            "raw_author": "Reviewer",
            "pdf_page": 25,
            "book_page": "17",
            "comment": "Right annotation",
            "rect_x0": 400,
            "rect_y0": 200,
            "rect_x1": 450,
            "rect_y1": 220,
        },
    ]

    prepared = prepare_v2_entries(
        source_entries,
        document_key="TEST_DOCUMENT",
        sha256="a" * 64,
    )

    canonical = [
        _canonical_entry(
            "TEST_DOCUMENT",
            item,
            first_seen="2026-10-13",
            last_seen="2026-10-13",
        )
        for item in prepared
    ]

    assert all(row["Coordinates"] for row in canonical)

    for row in canonical:
        decoded = json.loads(row["Coordinates"])
        assert "rect_x0" in decoded
        assert "rect_y0" in decoded

    result = project_backend_rows(canonical)

    assert [
        row["Root Entry ID"]
        for row in result["rows"]
    ] == ["RIGHT", "LEFT"]

    assert result["root_count"] == 2
