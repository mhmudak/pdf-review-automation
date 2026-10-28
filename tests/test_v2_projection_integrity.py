import json

from v2_output_projection import project_entries


def entry(entry_id, relation="ROOT", parent="", **extra):
    result = {
        "entry_id": entry_id,
        "relation_type": relation,
        "parent_entry_id": parent,
        "book_page": "17",
        "pdf_page": 25,
        "comment": entry_id,
    }
    result.update(extra)
    return result


def test_orphan_group_retains_original_identity():
    result = project_entries([
        entry("G1", "GROUP", "MISSING"),
    ])

    row = result["rows"][0]

    assert result["root_count"] == 1
    assert row["Root Entry ID"] == "G1"
    assert row["Relation Type"] == "GROUP"
    assert row["Parent Entry ID"] == "MISSING"


def test_linked_group_parent_is_auditable():
    result = project_entries([
        entry("ROOT"),
        entry("GROUP1", "GROUP", "ROOT"),
    ])

    row = result["rows"][0]
    links = json.loads(row["Group Parent Links"])

    assert result["root_count"] == 1
    assert result["group_count"] == 1
    assert links == [{
        "entry_id": "GROUP1",
        "parent_entry_id": "ROOT",
        "relation_type": "GROUP",
    }]


def test_reply_to_orphan_group_is_preserved():
    result = project_entries([
        entry("G1", "GROUP", "MISSING"),
        entry(
            "R1",
            "REPLY",
            "G1",
            created="2026-10-13T10:00:00+03:00",
        ),
    ])

    assert result["root_count"] == 1
    assert result["reply_count"] == 1
    assert result["rows"][0]["Reply Entry IDs"] == "R1"
    assert "R1" in result["rows"][0]["Reply 1"]


def test_nested_reply_and_group_chain():
    result = project_entries([
        entry("ROOT"),
        entry(
            "R1",
            "REPLY",
            "ROOT",
            created="2026-10-13T10:00:00+03:00",
        ),
        entry(
            "R2",
            "REPLY",
            "R1",
            created="2026-10-13T11:00:00+03:00",
        ),
        entry("G1", "GROUP", "ROOT"),
        entry("G2", "GROUP", "G1"),
    ])

    assert result["root_count"] == 1
    assert result["reply_count"] == 2
    assert result["group_count"] == 2

    row = result["rows"][0]

    assert row["Reply Entry IDs"] == "R1, R2"
    assert row["Group Entry IDs"] == "G1, G2"

    links = json.loads(row["Group Parent Links"])
    parents = {
        item["entry_id"]: item["parent_entry_id"]
        for item in links
    }

    assert parents == {
        "G1": "ROOT",
        "G2": "G1",
    }
