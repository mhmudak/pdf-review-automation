import json

from v2_model import prepare_v2_entries


def make_entry(**overrides):
    entry = {
        "entry_id": "test-coordinate-1",
        "raw_author": "Test Reviewer",
        "relation_type": "ROOT",
        "pdf_page": 25,
        "book_page": "17",
        "comment": "Example comment",
        "rect_x0": 100.0,
        "rect_y0": 200.5,
        "rect_x1": 150.0,
        "rect_y1": 215.0,
    }
    entry.update(overrides)
    return entry


def prepare(entry):
    return prepare_v2_entries(
        [entry],
        document_key="TEST_DOCUMENT",
        sha256="a" * 64,
    )[0]


def test_coordinates_are_serialized():
    result = prepare(make_entry())

    assert json.loads(result["coordinates"]) == {
        "rect_x0": 100.0,
        "rect_y0": 200.5,
        "rect_x1": 150.0,
        "rect_y1": 215.0,
    }


def test_coordinates_missing_are_empty():
    result = prepare(make_entry(rect_y0=None))

    assert result["coordinates"] == ""


def test_zero_coordinates_are_preserved():
    result = prepare(make_entry(
        rect_x0=0,
        rect_y0=0,
    ))

    coordinates = json.loads(result["coordinates"])

    assert coordinates["rect_x0"] == 0
    assert coordinates["rect_y0"] == 0
