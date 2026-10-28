import json

import pytest

from v2_output_projection import project_backend_rows


def backend_entry(entry_id, relation="ROOT", **extra):
    record = {
        "Entry ID": entry_id,
        "Parent Entry ID": "",
        "Relation Type": relation,
        "Book Page": "17",
        "PDF Page": 25,
        "Content": entry_id,
        "Canonical Author": "Hala Afifi",
        "Modified Date": "2026-10-01T12:00:00+03:00",
        "Active": True,
    }
    record.update(extra)
    return record


def coordinates(x, y):
    return json.dumps({
        "rect_x0": x,
        "rect_y0": y,
        "rect_x1": x + 15,
        "rect_y1": y + 10,
    })


def test_backend_rows_sort_top_to_bottom():
    records = [
        backend_entry("LOW", Coordinates=coordinates(100, 400)),
        backend_entry("HIGH", Coordinates=coordinates(100, 100)),
    ]

    output = project_backend_rows(records)

    assert [
        row["Root Entry ID"]
        for row in output["rows"]
    ] == ["HIGH", "LOW"]


def test_backend_rows_sort_right_to_left():
    records = [
        backend_entry("LEFT", Coordinates=coordinates(100, 100)),
        backend_entry("RIGHT", Coordinates=coordinates(400, 100)),
    ]

    output = project_backend_rows(records)

    assert [
        row["Root Entry ID"]
        for row in output["rows"]
    ] == ["RIGHT", "LEFT"]


def test_backend_dynamic_four_replies_and_group():
    records = [backend_entry("ROOT")]

    for number in range(4):
        records.append(
            backend_entry(
                f"R{number + 1}",
                "REPLY",
                **{
                    "Parent Entry ID": "ROOT",
                    "Created Date":
                        f"2026-10-01T10:0{number}:00+03:00",
                },
            )
        )

    records.append(
        backend_entry(
            "GROUP1",
            "GROUP",
            **{"Parent Entry ID": "ROOT"},
        )
    )

    output = project_backend_rows(records)

    assert output["root_count"] == 1
    assert output["reply_count"] == 4
    assert output["group_count"] == 1
    assert output["reply_columns"] == 4
    assert output["rows"][0]["Group Entry IDs"] == "GROUP1"
    assert output["rows"][0]["Reply Entry IDs"] == (
        "R1, R2, R3, R4"
    )


def test_inactive_backend_entries_are_excluded():
    records = [
        backend_entry("ACTIVE"),
        backend_entry("INACTIVE", Active=False),
    ]

    output = project_backend_rows(records)

    assert output["root_count"] == 1


def test_missing_coordinates_use_fallback():
    records = [
        backend_entry("B", Coordinates="invalid"),
        backend_entry("A", Coordinates=""),
    ]

    output = project_backend_rows(records)

    assert output["root_count"] == 2
    assert {
        row["Root Entry ID"]
        for row in output["rows"]
    } == {"A", "B"}


def test_orphan_replies_fail_without_data_loss():
    records = [
        backend_entry(
            "ORPHAN",
            "REPLY",
            **{"Parent Entry ID": "MISSING"},
        )
    ]

    with pytest.raises(ValueError, match="orphan replies"):
        project_backend_rows(records)


def test_undated_reply4_appends_after_three_dated_replies():
    # Reproduces staging root 79d2a07e...: Reply 4 has no PDF
    # creation/modification dates and must not be placed first.
    root = backend_entry("ROOT")
    dated = [
        backend_entry(
            f"dated-{i}", "REPLY",
            **{"Parent Entry ID": "ROOT",
               "Created Date": f"2026-10-0{i}T07:40:00+03:00"},
        ) for i in range(1, 4)
    ]
    undated = backend_entry(
        "props-qa-reply4-20261026", "REPLY",
        **{"Parent Entry ID": "ROOT",
           "Created Date": "", "Modified Date": ""},
    )
    previous = project_backend_rows([root, *dated])["rows"][0]
    current = project_backend_rows([undated, root, *reversed(dated)])["rows"][0]
    assert previous["Reply Entry IDs"] == "dated-1, dated-2, dated-3"
    assert current["Reply Entry IDs"] == (
        "dated-1, dated-2, dated-3, props-qa-reply4-20261026"
    )
    assert current["Reply 4"].startswith("Hala Afifi ? props-qa-reply4")


def test_undated_replies_are_deterministic_across_input_order():
    root = backend_entry("ROOT")
    dated = backend_entry("dated", "REPLY", **{
        "Parent Entry ID": "ROOT",
        "Created Date": "2026-10-01T07:40:00+03:00",
    })
    undated = [backend_entry(name, "REPLY", **{
        "Parent Entry ID": "ROOT", "Created Date": "", "Modified Date": ""
    }) for name in ("z-undated", "a-undated")]
    rows = [[root, dated, *undated], [*reversed(undated), dated, root]]
    assert [project_backend_rows(row)["rows"][0]["Reply Entry IDs"] for row in rows] == [
        "dated, a-undated, z-undated", "dated, a-undated, z-undated"
    ]
