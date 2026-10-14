from v2_output_projection import project_entries


def make_entry(entry_id, relation, parent="", page=17):
    return {
        "entry_id": entry_id,
        "relation_type": relation,
        "parent_entry_id": parent,
        "book_page": str(page),
        "pdf_page": page + 8,
        "comment": entry_id,
        "rect_x0": 100,
        "rect_y0": 100,
    }


def test_orphan_group_becomes_visible():
    entries = [
        make_entry("ROOT", "ROOT"),
        make_entry("ORPHAN", "GROUP", "MISSING", 18),
    ]

    result = project_entries(entries)

    assert result["root_count"] == 2
    assert result["group_count"] == 1
    assert len(result["orphan_groups"]) == 1
    assert [
        row["Root Entry ID"]
        for row in result["rows"]
    ] == ["ROOT", "ORPHAN"]


def test_linked_group_remains_audit_only():
    entries = [
        make_entry("ROOT", "ROOT"),
        make_entry("GROUP1", "GROUP", "ROOT"),
    ]

    result = project_entries(entries)

    assert result["root_count"] == 1
    assert len(result["rows"]) == 1
    assert result["rows"][0]["Group Entry IDs"] == "GROUP1"
    assert result["group_count"] == 1
    assert result["orphan_groups"] == []


def test_two_orphan_groups_are_not_lost():
    entries = [
        make_entry("ROOT", "ROOT"),
        make_entry("G1", "GROUP", "MISSING1", 18),
        make_entry("G2", "GROUP", "MISSING2", 19),
    ]

    result = project_entries(entries)

    assert result["root_count"] == 3
    assert result["group_count"] == 2
    assert len(result["rows"]) == 3
    assert len(result["orphan_groups"]) == 2
